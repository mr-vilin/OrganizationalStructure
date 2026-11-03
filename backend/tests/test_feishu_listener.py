from types import SimpleNamespace
from test_sync_persistence import sessions
from app.config import Settings
from app.persistence.models import SyncJob, SystemSetting, EventInbox
from sqlalchemy import select
import pytest


def test_listener_startup_and_reconnected_enqueue_one_reconcile_without_claiming_connected(sessions):
    from app.feishu.listener import Listener
    listener=Listener(sessions,Settings(feishu_app_id='a',feishu_app_secret='s',feishu_tenant_key='t'))
    listener.starting()
    listener.starting()
    with sessions() as db:
        assert len(list(db.scalars(select(SyncJob)))) == 1
        assert 'degraded' in db.get(SystemSetting,'feishu_connection_observation').value
    listener.reconnected()
    with sessions() as db: assert len(list(db.scalars(select(SyncJob)))) == 1


def test_listener_callback_only_inboxes_and_never_swallows_persistence_failure(sessions):
    from app.feishu.listener import Listener
    listener=Listener(sessions,Settings(feishu_app_id='a',feishu_app_secret='s',feishu_tenant_key='t'))
    payload={'header':{'event_id':'e','event_type':'contact.user.created_v3','app_id':'a','tenant_key':'t'},'event':{'object':{'user_id':'u'}}}
    listener.receive(payload)
    listener.receive(payload)
    with sessions() as db: assert db.get(EventInbox,'e').status == 'queued'


def test_listener_remains_available_before_initialization_and_resumes_reconcile(sessions):
    from app.feishu.listener import Listener
    from app.persistence.models import DatasetState
    with sessions.begin() as db:
        db.get(DatasetState, 1).initialization_status = 'pending'
    listener = Listener(sessions, Settings(feishu_app_id='a', feishu_app_secret='s', feishu_tenant_key='t'))
    listener.starting()
    listener.reconnected()
    listener.receive({'header': {'event_id': 'before-init', 'event_type': 'contact.scope.updated_v3',
                                 'app_id': 'a', 'tenant_key': 't'}, 'event': {}})
    with sessions() as db:
        assert list(db.scalars(select(SyncJob))) == []
        assert db.get(EventInbox, 'before-init').status == 'queued'
        assert db.get(SystemSetting, 'coverage_invalidated').value == 'true'
        assert 'connected' in db.get(SystemSetting, 'feishu_connection_observation').value
    with sessions.begin() as db:
        db.get(DatasetState, 1).initialization_status = 'complete'
    listener.reconnected()
    with sessions() as db:
        assert len(list(db.scalars(select(SyncJob)))) == 1


def test_listener_does_not_hide_unexpected_reconcile_failures(sessions, monkeypatch):
    from app.feishu.listener import Listener, SqlSyncJobRepository
    def fail(*args, **kwargs):
        raise RuntimeError('DATABASE_SCHEMA_INCOMPLETE')
    monkeypatch.setattr(SqlSyncJobRepository, 'submit', fail)
    listener = Listener(sessions, Settings())
    with pytest.raises(RuntimeError, match='DATABASE_SCHEMA_INCOMPLETE'):
        listener.starting()
