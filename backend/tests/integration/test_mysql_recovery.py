"""恢复操作必须在真实 MySQL 上验证；缺少测试库时明确跳过。"""
from datetime import datetime, timedelta
from pathlib import Path
import sys
from uuid import uuid4

import pytest
import hashlib
from sqlalchemy import event, select

from app.persistence.models import AdminAllowlist, AdminSession, ApiClient, ChangeLog, DatasetState, EventInbox, OAuthState, SyncJob, WorkerLease

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from deploy.recovery import reset_restored_state


def seed_credentials(sessions):
    token = uuid4().hex
    now = datetime(2026, 9, 15)
    with sessions.begin() as db:
        old_epoch = db.get(DatasetState, 1).dataset_epoch
        db.add(AdminSession(id='internal-restore', token_digest=hashlib.sha256(token.encode()).hexdigest(), open_id='ou_restore', csrf_hash='x' * 64,
                            expires_at=now + timedelta(days=1)))
        db.add(ApiClient(id=token, name='恢复测试', secret_hash='x' * 64, created_at=now))
    return token, old_epoch


def test_restore_requires_new_epoch_initialization_and_new_credentials(mysql_sessions):
    token, old_epoch = seed_credentials(mysql_sessions)
    now = datetime(2026, 9, 15)
    with mysql_sessions.begin() as db:
        db.add(OAuthState(digest=token, expires_at=now + timedelta(hours=1)))
        lease = db.get(WorkerLease, 1)
        assert lease is not None, '请执行完整迁移链以建立 worker 租约'
        lease.owner, lease.generation, lease.expires_at = 'old-worker', 10, now + timedelta(hours=1)
        db.add(SyncJob(id=token, type='full', requested_by='recovery-test', status='running',
                       lease_generation=4, lease_expires_at=now + timedelta(hours=1), created_at=now, updated_at=now))
        db.add(EventInbox(event_id=token, event_type='contact.user.updated_v3', payload={}, status='queued', received_at=now))
    recovery_admin = 'ou_recovery_' + uuid4().hex
    new_epoch = reset_restored_state(mysql_sessions, actor='integration-restore', admin_open_id=recovery_admin)
    with mysql_sessions() as db:
        state = db.get(DatasetState, 1)
        assert state.dataset_epoch == new_epoch != old_epoch
        assert state.initialization_status == 'pending'
        assert state.data_version == 0
        assert state.coverage_status == 'unknown'
        assert state.last_full_sync_at is None
        assert db.get(AdminSession, 'internal-restore').revoked_at is not None
        assert db.get(ApiClient, token).revoked_at is not None
        assert db.get(AdminAllowlist, recovery_admin) is not None
        assert db.get(OAuthState, token) is None
        assert db.get(WorkerLease, 1).generation == 11
        assert db.get(WorkerLease, 1).owner is None
        assert db.get(SyncJob, token).status == 'failed'
        assert db.get(SyncJob, token).lease_generation == 5
        assert db.get(EventInbox, token).status == 'ignored_restored'
        log = db.scalar(select(ChangeLog).where(ChangeLog.source == 'recovery', ChangeLog.object_type == 'dataset').order_by(ChangeLog.id.desc()))
        assert log.after_data['dataset_epoch'] == new_epoch


def test_recovery_audit_failure_rolls_back_epoch_and_revocations(mysql_sessions):
    token, old_epoch = seed_credentials(mysql_sessions)

    def fail_audit(db, _context, _instances):
        if any(isinstance(row, ChangeLog) and row.source == 'recovery' for row in db.new):
            raise RuntimeError('injected recovery audit failure')

    event.listen(mysql_sessions.class_, 'before_flush', fail_audit)
    try:
        with pytest.raises(RuntimeError, match='injected recovery audit failure'):
            reset_restored_state(mysql_sessions, actor='integration-restore')
    finally:
        event.remove(mysql_sessions.class_, 'before_flush', fail_audit)
    with mysql_sessions() as db:
        assert db.get(DatasetState, 1).dataset_epoch == old_epoch
        assert db.get(AdminSession, 'internal-restore').revoked_at is None
        assert db.get(ApiClient, token).revoked_at is None
