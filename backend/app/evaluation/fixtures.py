"""隔离 MySQL 评测夹具。调用方必须停止 Worker 后串行 reset/seed/读基线。"""
from contextlib import contextmanager
from copy import deepcopy
import json

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker

from app.evaluation.cases import validate_case
from app.evaluation.models import EvaluationCase
from app.persistence.database import CURRENT_SCHEMA_HEAD, create_mysql_engine, session_factory
from app.persistence import models as m


FAKE_APP_ID = 'eval-fake-app'
FAKE_TENANT_KEY = 'eval-fake-tenant'
_DISABLED_SCHEDULE = json.dumps({'enabled': False, 'local_time': '03:00', 'timezone': 'Asia/Shanghai', 'updated_at': None})
_SECTIONS = (
    ('departments', m.Department), ('employees', m.Employee),
    ('employee_departments', m.EmployeeDepartment), ('store_profiles', m.StoreProfile),
    ('employee_stores', m.EmployeeStore),
)


def _validate_url(database_url):
    try:
        parsed = make_url(database_url)
    except Exception:
        raise ValueError('EVALUATION_TEST_DATABASE_REQUIRED') from None
    if parsed.drivername != 'mysql+pymysql' or not (parsed.database or '').endswith('_test'):
        raise ValueError('EVALUATION_TEST_DATABASE_REQUIRED')
    return parsed


def verify_test_database(connection) -> dict:
    """在实际操作连接核实目标、会话和现有迁移；失败发生在任何业务写入之前。"""
    parsed = _validate_url(connection.engine.url)
    row = connection.execute(text('SELECT DATABASE(), VERSION(), @@transaction_isolation, '
                                  '@@character_set_client, @@character_set_connection, '
                                  '@@character_set_results, @@collation_connection')).one()
    if row[0] != parsed.database or not row[0].endswith('_test'):
        raise ValueError('EVALUATION_TEST_DATABASE_MISMATCH')
    if not row[1].startswith('8.4.') or row[2] != 'REPEATABLE-READ':
        raise ValueError('EVALUATION_MYSQL_CONFIGURATION_MISMATCH')
    if tuple(row[3:]) != ('utf8mb4', 'utf8mb4', 'utf8mb4', 'utf8mb4_general_ci'):
        raise ValueError('EVALUATION_MYSQL_CHARSET_MISMATCH')
    schema = connection.execute(text('SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME '
                                     'FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=DATABASE()')).one()
    if tuple(schema) != ('utf8mb4', 'utf8mb4_general_ci'):
        raise ValueError('EVALUATION_MYSQL_SCHEMA_MISMATCH')
    revisions = connection.scalars(text('SELECT version_num FROM alembic_version')).all()
    if revisions != [CURRENT_SCHEMA_HEAD]:
        raise ValueError('EVALUATION_MIGRATION_HEAD_MISMATCH')
    columns = connection.execute(text('SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS '
                                      'WHERE TABLE_SCHEMA=DATABASE()')).all()
    actual = {}
    for table, column in columns:
        actual.setdefault(table, set()).add(column)
    for table in m.Base.metadata.tables.values():
        if actual.get(table.name) != set(table.columns.keys()):
            raise ValueError('EVALUATION_DATABASE_STRUCTURE_MISMATCH')
    # 不接受额外业务表被遗漏清理；迁移记录是唯一 ORM 外的允许表。
    if set(actual) != {*m.Base.metadata.tables, 'alembic_version'}:
        raise ValueError('EVALUATION_DATABASE_TABLES_MISMATCH')
    incompatible = connection.scalar(text('''SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE k
        JOIN information_schema.COLUMNS c ON c.TABLE_SCHEMA=k.TABLE_SCHEMA AND c.TABLE_NAME=k.TABLE_NAME AND c.COLUMN_NAME=k.COLUMN_NAME
        JOIN information_schema.COLUMNS r ON r.TABLE_SCHEMA=k.REFERENCED_TABLE_SCHEMA AND r.TABLE_NAME=k.REFERENCED_TABLE_NAME AND r.COLUMN_NAME=k.REFERENCED_COLUMN_NAME
        WHERE k.TABLE_SCHEMA=DATABASE() AND k.REFERENCED_TABLE_NAME IS NOT NULL
        AND (c.COLUMN_TYPE<>r.COLUMN_TYPE OR NOT(c.CHARACTER_SET_NAME<=>r.CHARACTER_SET_NAME) OR NOT(c.COLLATION_NAME<=>r.COLLATION_NAME))'''))
    if incompatible:
        raise ValueError('EVALUATION_DATABASE_FOREIGN_KEY_MISMATCH')
    return {'database': row[0], 'mysql_version': row[1], 'isolation': row[2],
            'charset': row[3], 'collation': row[6], 'migration_head': revisions[0],
            'orm_table_count': len(m.Base.metadata.tables)}


def _require_quiet(connection):
    lease = connection.execute(select(m.WorkerLease.__table__).where(m.WorkerLease.id == 1).with_for_update()).mappings().first()
    # 即使租约已过期也要求执行方显式释放 owner；不能把线程超时当作取消。
    running = connection.scalar(select(m.SyncJob.id).where(m.SyncJob.status == 'running').limit(1))
    if (lease and lease['owner']) or running:
        raise RuntimeError('EVALUATION_WORKER_NOT_QUIET')


def _reset(connection):
    verify_test_database(connection)
    _require_quiet(connection)
    for table in reversed(m.Base.metadata.sorted_tables):
        if table.name == 'department':
            # 所有外部引用已删除；先断开可空自引用，避免 MySQL 同表 DELETE FK 限制。
            connection.execute(update(table).values(parent_id=None))
        connection.execute(delete(table))
    connection.execute(insert(m.DatasetState), [{'id': 1, 'dataset_epoch': 'pending', 'data_version': 0,
                                                'initialization_status': 'pending', 'coverage_status': 'unknown'}])
    connection.execute(insert(m.SystemSetting), [{'key': 'task_queue_lock', 'value': '1'},
                                                {'key': 'reconcile_schedule', 'value': _DISABLED_SCHEDULE}])
    connection.execute(insert(m.WorkerLease), [{'id': 1, 'generation': 0}])
    connection.execute(insert(m.FeishuConnection), [{'id': 1, 'app_id': FAKE_APP_ID, 'tenant_key': FAKE_TENANT_KEY,
                                                    'status': 'degraded', 'coverage_status': 'unknown', 'custom_attrs': {}}])


def reset_test_database(database_url: str) -> None:
    """事务化清除测试库所有业务/身份/运行行，保留 alembic 和安全基础单例。

    底层管理操作，调用方负责独占测试库；跨 case 使用 evaluation_database。
    """
    _validate_url(database_url)
    engine = create_mysql_engine(database_url)
    try:
        with engine.begin() as connection:
            _reset(connection)
    finally:
        engine.dispose()


def seed_case(factory: sessionmaker, case: EvaluationCase) -> None:
    """按 fixture 字面值写入；不计算投影、expected 或唯一 run_id。失败整笔回滚。"""
    case = validate_case(case)
    if not isinstance(factory, sessionmaker) or not isinstance(factory.kw.get('bind'), Engine):
        raise ValueError('EVALUATION_ENGINE_FACTORY_REQUIRED')
    _validate_url(factory.kw['bind'].url)
    fixture = deepcopy(case.fixture)
    allowed = {'dataset_state', 'system_settings', 'fake_feishu', *(name for name, _ in _SECTIONS)}
    if set(fixture) != allowed:
        raise ValueError('EVALUATION_FIXTURE_SECTIONS_INVALID')
    settings = fixture['system_settings']
    setting_keys = [row['key'] for row in settings]
    if len(set(setting_keys)) != len(setting_keys):
        raise ValueError('EVALUATION_FIXTURE_SETTINGS_DUPLICATE')
    schedule = next((row['value'] for row in settings if row['key'] == 'reconcile_schedule'), None)
    if schedule is None or json.loads(schedule).get('enabled') is not False:
        raise ValueError('EVALUATION_SCHEDULE_MUST_BE_DISABLED')
    if fixture['dataset_state'].get('id') != 1 or not str(fixture['dataset_state'].get('dataset_epoch', '')).startswith(('test-', 'test_')):
        raise ValueError('EVALUATION_DATASET_STATE_INVALID')
    with factory.begin() as db:
        connection = db.connection()
        verify_test_database(connection)
        _require_quiet(connection)
        baseline_counts = {'dataset_state': 1, 'system_setting': 2, 'worker_lease': 1, 'feishu_connection': 1}
        for table in m.Base.metadata.tables.values():
            if connection.scalar(select(func.count()).select_from(table)) != baseline_counts.get(table.name, 0):
                raise ValueError('EVALUATION_RESET_REQUIRED')
        state = db.get(m.DatasetState, 1)
        binding = db.get(m.FeishuConnection, 1)
        if (state is None or state.dataset_epoch != 'pending' or state.data_version != 0
                or binding is None or binding.app_id != FAKE_APP_ID or binding.tenant_key != FAKE_TENANT_KEY):
            raise ValueError('EVALUATION_RESET_REQUIRED')
        # 先提交前置禁用配置到本事务；Worker 只能在 seed 完整提交后启动。
        for row in settings:
            if row['key'] == 'task_queue_lock':
                raise ValueError('EVALUATION_RESERVED_SETTING')
            db.merge(m.SystemSetting(**row))
        db.flush()
        db.merge(m.DatasetState(**fixture['dataset_state']))
        db.flush()
        for section, model in _SECTIONS:
            # 部门必须按父先子后逐行 flush，禁止 ORM 自动排序掩盖非法 fixture。
            for row in fixture[section]:
                db.add(model(**row))
                db.flush()


@contextmanager
def evaluation_database(database_url: str):
    """跨独立连接的串行生命周期；finally 清理，活跃 Worker 会硬失败而不删除。"""
    _validate_url(database_url)
    engine = create_mysql_engine(database_url)
    try:
        with engine.connect() as lock:
            verify_test_database(lock)
            if lock.scalar(text("SELECT GET_LOCK('organization_evaluation_serial', 0)")) != 1:
                raise RuntimeError('EVALUATION_DATABASE_BUSY')
            lock.commit()
            try:
                reset_test_database(database_url)
                yield session_factory(engine)
            finally:
                try:
                    reset_test_database(database_url)
                finally:
                    lock.execute(text("SELECT RELEASE_LOCK('organization_evaluation_serial')"))
                    lock.commit()
    finally:
        engine.dispose()
