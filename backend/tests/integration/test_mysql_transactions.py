from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.persistence.models import AdminSession, ApiClient, ChangeLog, DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, StoreProfile
from app.persistence.read_service import SqlReadService
from app.persistence.repositories import SqlIdentityRepository
from app.stores.domain import StorePatch
from app.stores.service import StoreAdminService


def test_admin_removal_preserves_revoked_session_and_denies_authentication(mysql_sessions):
    now = datetime(2026, 9, 15, 3, 0)
    identity = SqlIdentityRepository(mysql_sessions, 't' * 32)
    open_id = 'ou_test_' + uuid4().hex
    identity.add_admin(open_id, 'integration', now)
    issued = identity.create_session(open_id, 'csrf', now + timedelta(hours=1), now)
    assert identity.authenticate_session(issued.token, now).open_id == open_id
    identity.remove_admin(open_id, 'integration', now)
    assert identity.authenticate_session(issued.token, now) is None
    with mysql_sessions() as db:
        assert db.get(AdminSession, issued.record.id).revoked_at == now


def test_failed_rotation_rolls_back_revocation_and_audit(mysql_sessions):
    now = datetime(2026, 9, 15, 3, 0)
    identity = SqlIdentityRepository(mysql_sessions, 't' * 32)
    old, secret = identity.create_api_key('test-' + uuid4().hex, 'integration', now)

    def fail_replacement(db, _context, _instances):
        if any(isinstance(row, ApiClient) and row.id != old.id for row in db.new):
            raise RuntimeError('injected write failure')

    event.listen(mysql_sessions.class_, 'before_flush', fail_replacement)
    try:
        with pytest.raises(RuntimeError, match='injected write failure'):
            identity.rotate_api_key(old.id, 'integration', now)
    finally:
        event.remove(mysql_sessions.class_, 'before_flush', fail_replacement)
    assert identity.authenticate_api_key(old.id, secret) is not None
    with mysql_sessions() as db:
        logs = list(db.scalars(select(ChangeLog).where(ChangeLog.object_id == old.id)))
        assert len(logs) == 1
        assert secret not in str(logs[0].after_data)


def test_store_marking_and_cancellation_publish_projection_with_version(mysql_sessions):
    now = datetime(2026, 9, 15, 3, 0)
    prefix = 'test_' + uuid4().hex
    shop, kitchen, user = prefix + '_shop', prefix + '_kitchen', prefix + '_user'
    with mysql_sessions.begin() as db:
        db.add(Department(id=shop, feishu_department_id=shop, name='测试店', status='active', sync_quality='verified', is_virtual_root=False))
        db.flush()
        db.add(Department(id=kitchen, feishu_department_id=kitchen, parent_id=shop, name='后厨', status='active', sync_quality='verified', is_virtual_root=False))
        db.flush()
        db.add(Employee(id=user, feishu_user_id=user, name='测试员工', status='active', sync_quality='verified', primary_department_id=kitchen))
        db.flush()
        db.add(EmployeeDepartment(employee_id=user, department_id=kitchen, active=True, is_primary=True))
    stores = StoreAdminService(mysql_sessions)
    stores.apply([StorePatch(shop, True, prefix, '保留备注')], 1, 'integration', now)
    with mysql_sessions() as db:
        assert db.get(DatasetState, 1).data_version == 2
        assert db.get(EmployeeStore, (user, shop)).is_primary is True
    stores.apply([StorePatch(shop, False)], 2, 'integration', now)
    with mysql_sessions() as db:
        assert db.get(DatasetState, 1).data_version == 3
        assert db.get(StoreProfile, shop).store_code == prefix
        assert db.get(StoreProfile, shop).notes == '保留备注'
        assert db.get(EmployeeStore, (user, shop)) is None


def test_cross_page_version_change_is_rejected(mysql_sessions):
    reads = SqlReadService(mysql_sessions, 'c' * 32)
    prefix = 'test_' + uuid4().hex
    with mysql_sessions.begin() as db:
        db.add_all([Department(id=prefix + str(n), feishu_department_id=prefix + str(n), name='测试部门', status='active', sync_quality='verified', is_virtual_root=False) for n in range(2)])
    _, meta = reads.list_departments(limit=1)
    assert meta['next_cursor']
    with mysql_sessions.begin() as db:
        db.get(DatasetState, 1).data_version += 1
    with pytest.raises(RuntimeError, match='DATASET_CHANGED'):
        reads.list_departments(limit=1, cursor=meta['next_cursor'])
