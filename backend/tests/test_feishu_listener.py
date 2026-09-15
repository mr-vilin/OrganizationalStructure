from types import SimpleNamespace
from test_sync_persistence import sessions
from app.config import Settings
from app.persistence.models import SyncJob, SystemSetting, EventInbox
from sqlalchemy import select


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
