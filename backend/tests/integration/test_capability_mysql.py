"""独立 MySQL 8.4 双事务验收；不使用单连接 savepoint 夹具。"""
import os
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.persistence.database import create_mysql_engine
from app.persistence.models import ChangeLog, DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, StoreCodeReservation, StoreProfile
from app.stores.domain import InvalidStoreChanges, StorePatch
from app.stores.service import StoreAdminService


@pytest.fixture
def independent_capability_mysql():
    url = os.environ.get('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('未提供 ORG_TEST_DATABASE_URL；MySQL 双事务旧快照验收未执行')
    parsed = make_url(url)
    if parsed.drivername != 'mysql+pymysql' or not (parsed.database or '').endswith('_test'):
        pytest.fail('仅允许 mysql+pymysql 且数据库名以 _test 结尾的独立测试库')
    engine = create_mysql_engine(url)
    sessions = sessionmaker(engine, expire_on_commit=False)
    prefix = 'cap_rr_' + uuid4().hex
    ids = {name: prefix + '_' + name for name in ['shop', 'other', 'leaf', 'u', 'w', 'new']}
    original = None
    try:
        with sessions.begin() as db:
            assert db.scalar(text('SELECT VERSION()')).startswith('8.4.'), '本用例要求 MySQL 8.4'
            assert db.scalar(text('SELECT @@transaction_isolation')) == 'REPEATABLE-READ'
            # 重建投影会触及整个数据集；要求专用测试库没有其它组织事实。
            assert db.scalar(select(func.count()).select_from(Department)) == 0, '请使用没有组织事实的独立 _test 库'
            assert db.scalar(select(func.count()).select_from(Employee)) == 0, '请使用没有组织事实的独立 _test 库'
            state = db.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
            assert state is not None, '请先执行现有 alembic upgrade head'
            original = {column.name: getattr(state, column.name) for column in DatasetState.__table__.columns if column.name != 'id'}
            state.dataset_epoch, state.data_version, state.initialization_status = prefix, 7, 'complete'
            db.add_all([Department(id=ids[key], feishu_department_id=ids[key], name=key, status='active', sync_quality='complete') for key in ['shop', 'other']])
            db.flush()
            db.add(Department(id=ids['leaf'], feishu_department_id=ids['leaf'], parent_id=ids['shop'], name='leaf', status='active', sync_quality='complete'))
            db.add(StoreProfile(department_id=ids['shop'], is_store=False, notes='old-notes'))
            db.add(StoreProfile(department_id=ids['other'], is_store=False))
            db.flush()
            for key in ['u', 'w']:
                db.add(Employee(id=ids[key], feishu_user_id=ids[key], name=key, primary_department_id=ids['leaf'], status='active', sync_quality='complete'))
            db.flush()
            for key in ['u', 'w']:
                db.add(EmployeeDepartment(employee_id=ids[key], department_id=ids['leaf'], active=True, is_primary=True))
        yield sessions, ids, prefix
    finally:
        if original is not None:
            with sessions.begin() as db:
                state = db.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
                db.execute(delete(ChangeLog).where(ChangeLog.actor == prefix))
                db.execute(delete(EmployeeStore).where(EmployeeStore.employee_id.in_([ids[k] for k in ['u', 'w', 'new']])))
                db.execute(delete(EmployeeDepartment).where(EmployeeDepartment.employee_id.in_([ids[k] for k in ['u', 'w', 'new']])))
                db.execute(delete(Employee).where(Employee.id.in_([ids[k] for k in ['u', 'w', 'new']])))
                db.execute(delete(StoreCodeReservation).where(StoreCodeReservation.department_id.in_([ids['shop'], ids['other']])))
                db.execute(delete(StoreProfile).where(StoreProfile.department_id.in_([ids['shop'], ids['other']])))
                db.execute(delete(Department).where(Department.id == ids['leaf']))
                db.execute(delete(Department).where(Department.id.in_([ids['shop'], ids['other']])))
                for key, value in original.items(): setattr(state, key, value)
        engine.dispose()


def test_borrowed_rr_uses_current_notes_and_all_projection_dependencies(independent_capability_mysql):
    sessions, ids, actor = independent_capability_mysql
    stores = StoreAdminService(sessions)
    with sessions() as reader, reader.begin():
        connection_a = reader.scalar(text('SELECT CONNECTION_ID()'))
        # 事务 A 此处建立 Read View，并保留 ORM 对象缓存；一直不结束该事务。
        assert reader.scalar(select(DatasetState.data_version)) == 7
        cached = [*reader.scalars(select(StoreProfile)), *reader.scalars(select(Department)),
                  *reader.scalars(select(Employee)), *reader.scalars(select(EmployeeDepartment))]
        with sessions.begin() as writer:
            assert writer.scalar(text('SELECT CONNECTION_ID()')) != connection_a
            state = writer.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
            writer.get(StoreProfile, ids['shop']).notes = 'committed-notes'
            writer.get(StoreProfile, ids['other']).is_store = True
            writer.get(Department, ids['leaf']).parent_id = ids['other']
            writer.get(Employee, ids['u']).status = 'inactive'
            writer.get(EmployeeDepartment, (ids['w'], ids['leaf'])).active = False
            writer.add(Employee(id=ids['new'], feishu_user_id=ids['new'], name='new', primary_department_id=ids['leaf'], status='active', sync_quality='complete'))
            writer.flush()
            writer.add(EmployeeDepartment(employee_id=ids['new'], department_id=ids['leaf'], active=True, is_primary=True))
            state.data_version = 8
        assert reader.scalar(select(DatasetState.data_version)) == 7
        assert cached  # 缓存对象在借用事务调用期间保持存活。
        result = stores.apply_in_session(reader, [StorePatch(ids['shop'], True)], 8, actor, datetime.now())
        assert (result.data_version, result.changed_count) == (9, 1)
    with sessions() as db:
        assert db.get(StoreProfile, ids['shop']).notes == 'committed-notes'
        log = db.get(ChangeLog, result.audit_ids[0])
        assert log.before_data['notes'] == log.after_data['notes'] == 'committed-notes'
        assert db.get(EmployeeStore, (ids['u'], ids['shop'])) is None
        assert db.get(EmployeeStore, (ids['w'], ids['shop'])) is None
        assert list(db.scalars(select(EmployeeStore).where(EmployeeStore.employee_id.in_([ids['u'], ids['w']])))) == []
        projection = db.get(EmployeeStore, (ids['new'], ids['other']))
        assert projection.is_primary and projection.path == [ids['leaf'], ids['other']]
        assert db.get(Employee, ids['u']).primary_store_status == 'inactive'
        assert db.get(Employee, ids['w']).primary_store_status == 'inconsistent'
        assert db.get(Employee, ids['new']).primary_store_status == 'resolved'
        assert db.get(DatasetState, 1).data_version == 9


@pytest.mark.parametrize('dependency,error_code', [('department', 'DEPARTMENT_INACTIVE'), ('reservation', 'STORE_CODE_RESERVED')])
def test_borrowed_rr_validates_current_department_and_code_reservation(independent_capability_mysql, dependency, error_code):
    sessions, ids, actor = independent_capability_mysql
    code = actor + '_code'
    with sessions() as reader, reader.begin():
        connection_a = reader.scalar(text('SELECT CONNECTION_ID()'))
        assert reader.scalar(select(DatasetState.data_version)) == 7
        cached_department = reader.get(Department, ids['shop'])
        assert reader.get(StoreCodeReservation, code) is None
        with sessions.begin() as writer:
            assert writer.scalar(text('SELECT CONNECTION_ID()')) != connection_a
            state = writer.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
            if dependency == 'department': writer.get(Department, ids['shop']).status = 'inactive'
            else: writer.add(StoreCodeReservation(store_code=code, department_id=ids['other'], reserved_at=datetime.now()))
            state.data_version = 8
        assert cached_department.status == 'active'
        assert reader.scalar(select(DatasetState.data_version)) == 7
        with pytest.raises(InvalidStoreChanges) as caught:
            StoreAdminService(sessions).apply_in_session(reader, [StorePatch(ids['shop'], True, code)], 8, actor, datetime.now())
        assert [error.code for error in caught.value.errors] == [error_code]
    with sessions() as db:
        assert db.get(StoreProfile, ids['shop']).is_store is False
        assert db.get(DatasetState, 1).data_version == 8
        assert list(db.scalars(select(ChangeLog).where(ChangeLog.actor == actor))) == []
