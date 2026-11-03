"""MySQL 8.4 上验证一次性切换、并发启动及清理事务。"""
from concurrent.futures import ThreadPoolExecutor

from alembic import command
import pytest
from sqlalchemy import event, select, text

from app.initialization.service import InitializationService, load_flow, save_flow, utcnow
from app.persistence.database import database_ready, session_factory
from app.persistence.models import AdminAllowlist, ChangeLog, DatasetState, Department, Employee, FeishuConnection, SyncJob, SystemSetting, WorkerLease
from app.sync.collector import Collector
from app.sync.worker import Worker
from test_initialization_wizard import Feishu, MAPPINGS, ready
from app.config import Settings


def configured(sessions):
    settings = Settings(session_secret='s' * 32, feishu_app_id='app', feishu_app_secret='isolated-secret',
                        feishu_tenant_key='tenant', feishu_redirect_uri='https://test.invalid/admin/auth/callback')
    with sessions.begin() as db:
        db.get(DatasetState, 1).initialization_status = 'pending'
        connection = db.get(FeishuConnection, 1)
        if connection is None:
            db.add(FeishuConnection(id=1, app_id='app', tenant_key='tenant', status='connected', custom_attrs=MAPPINGS))
        else:
            connection.app_id, connection.tenant_key, connection.custom_attrs = 'app', 'tenant', MAPPINGS
        lease = db.get(WorkerLease, 1)
        lease.owner, lease.expires_at = None, None
    api = Feishu()
    return InitializationService(sessions, settings, api), api, settings


def test_old_complete_instance_requires_one_new_initialization_and_upgrade_is_not_repeated(migration_database):
    engine, config = migration_database
    command.upgrade(config, '0009_operation_receipt')
    with engine.begin() as db:
        db.execute(text("UPDATE dataset_state SET initialization_status='complete', coverage_status='complete' WHERE id=1"))
        db.execute(text("INSERT INTO department (id,feishu_department_id,name,status,sync_quality,is_virtual_root) VALUES ('old','old','旧部门','active','complete',0)"))
        db.execute(text("INSERT INTO admin_allowlist (open_id,created_at) VALUES ('ou',UTC_TIMESTAMP())"))
    command.upgrade(config, 'head')
    assert database_ready(engine)['schema'] == 'ready'
    sessions = session_factory(engine)
    with sessions() as db:
        assert db.get(DatasetState, 1).initialization_status == 'pending'
        assert load_flow(db)['phase'] == 'cleanup_required'
        assert db.get(Department, 'old') is not None
        assert db.get(AdminAllowlist, 'ou') is not None
        report = db.execute(text('SELECT VERSION(), @@character_set_connection, @@collation_connection')).one()
        assert report[0].startswith('8.4.') and report[1:] == ('utf8mb4', 'utf8mb4_general_ci')
    service, api, settings = configured(sessions)
    service.restart('admin:ou')
    ready(service)
    job_id = service.start('admin:ou')
    worker = Worker(sessions, Collector(api), initialization_settings=settings)
    assert worker.acquire(utcnow()) and worker.step()
    assert service.status()['complete']
    command.upgrade(config, 'head')
    with sessions() as db:
        assert db.get(DatasetState, 1).initialization_status == 'complete'
        assert db.get(SyncJob, job_id).status == 'succeeded'
        assert db.get(Employee, 'v') is not None


def test_concurrent_administrators_share_one_initialization_job(migration_database):
    engine, config = migration_database
    command.upgrade(config, 'head')
    sessions = session_factory(engine)
    service, _, settings = configured(sessions)
    ready(service)
    def start(actor):
        return InitializationService(sessions, settings).start(actor)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, ['admin:a', 'admin:b']))
    assert results[0] == results[1]
    with sessions() as db:
        assert len(list(db.scalars(select(SyncJob).where(SyncJob.type == 'initialize')))) == 1


def test_cleanup_error_rolls_back_business_deletes_and_keeps_retry_available(migration_database):
    engine, config = migration_database
    command.upgrade(config, '0009_operation_receipt')
    with engine.begin() as db:
        db.execute(text("INSERT INTO department (id,feishu_department_id,name,status,sync_quality,is_virtual_root) VALUES ('old','old','旧部门','active','complete',0)"))
    command.upgrade(config, 'head')
    sessions = session_factory(engine)
    service, _, _ = configured(sessions)
    def fail_cleanup(_mapper, _connection, row):
        if row.object_type == 'initialization' and row.after_data.get('action') == 'cleanup':
            raise RuntimeError('TEST_AUDIT_FAILURE')
    event.listen(ChangeLog, 'before_insert', fail_cleanup)
    try:
        with pytest.raises(RuntimeError, match='TEST_AUDIT_FAILURE'):
            service.restart('admin:ou')
    finally:
        event.remove(ChangeLog, 'before_insert', fail_cleanup)
    with sessions() as db:
        assert db.get(Department, 'old') is not None
        assert load_flow(db)['phase'] == 'cleanup_required'
    assert service.restart('admin:ou')['phase'] == 'pending'


def test_large_enterprise_evidence_roundtrips_without_exceeding_text_columns(migration_database):
    engine, config = migration_database
    command.upgrade(config, 'head')
    sessions = session_factory(engine)
    flow = {'flow_id': 'large', 'phase': 'pending', 'checks': [], 'evidence': {
        'reference': '隔离测试大企业名单', 'employee_ids': [f'employee-{i:06d}' for i in range(8000)],
        'departmentless_ids': []}}
    with sessions.begin() as db:
        save_flow(db, flow)
    with sessions() as db:
        assert load_flow(db) == flow
        chunks = list(db.scalars(select(SystemSetting).where(SystemSetting.key.like('initialization_flow:chunk:%'))))
        assert len(chunks) > 1 and all(len(row.value.encode('utf-8')) <= 48000 for row in chunks)
    with sessions.begin() as db:
        save_flow(db, {'flow_id': 'small', 'phase': 'pending', 'checks': [], 'evidence': None})
    with sessions() as db:
        assert list(db.scalars(select(SystemSetting).where(SystemSetting.key.like('initialization_flow:chunk:%')))) == []
