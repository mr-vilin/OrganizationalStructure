"""初始化前的真实 Worker 队列回归；不能被较早的核对任务饿死。"""
from datetime import timedelta

from app.persistence.models import DatasetState, EventInbox, SyncJob, WorkerLease
from app.persistence.repositories import SqlSyncJobRepository
from app.sync.collector import Candidate
from app.sync.worker import Worker, utcnow
from app.config import Settings
from app.initialization.service import InitializationService
from app.persistence.models import FeishuConnection
from test_initialization_wizard import Feishu, MAPPINGS, ready


class CountingCollector:
    def __init__(self):
        self.calls = 0
        self.api = Feishu()

    def collect(self, root=None, **kwargs):
        self.calls += 1
        return Candidate(full=True)


def pending_worker(sessions):
    now = utcnow()
    with sessions.begin() as db:
        state = db.get(DatasetState, 1)
        state.initialization_status = "pending"
        lease = db.get(WorkerLease, 1)
        if lease is None:
            db.add(WorkerLease(id=1, generation=0))
        else:
            lease.owner, lease.expires_at = None, None
    collector = CountingCollector()
    settings = Settings(session_secret='s'*32, feishu_app_id='app', feishu_app_secret='test-secret', feishu_tenant_key='tenant', feishu_redirect_uri='https://test.invalid/admin/auth/callback')
    with sessions.begin() as db:
        connection = db.get(FeishuConnection, 1)
        if connection is None:
            db.add(FeishuConnection(id=1, app_id='app', tenant_key='tenant', status='connected', custom_attrs=MAPPINGS))
        else:
            connection.app_id, connection.tenant_key, connection.custom_attrs = 'app', 'tenant', MAPPINGS
    worker = Worker(sessions, collector, owner="test-initialization-queue", initialization_settings=settings)
    worker.initialization_service = InitializationService(sessions, settings, collector.api)
    assert worker.acquire(now)
    jobs = SqlSyncJobRepository(sessions)
    return worker, collector, jobs, now


def old_queued_job(sessions, job_type, now):
    # 模拟切换前遗留的任务；普通提交入口现在禁止初始化前创建业务同步。
    job = SyncJob(id='legacy-' + job_type, type=job_type, requested_by='legacy', status='queued', created_at=now, updated_at=now)
    with sessions.begin() as db:
        db.add(job)
    return job


def initialization_job(worker, sessions):
    ready(worker.initialization_service)
    job_id = worker.initialization_service.start('admin:ou')
    with sessions() as db:
        return db.get(SyncJob, job_id)


def assert_initialization_is_not_starved(sessions):
    worker, collector, jobs, now = pending_worker(sessions)
    reconcile = old_queued_job(sessions, 'reconcile', now-timedelta(minutes=2))
    initialize = initialization_job(worker, sessions)
    assert worker.step() is True
    with sessions() as db:
        assert db.get(SyncJob, initialize.id).status == "succeeded"
        assert db.get(SyncJob, reconcile.id).status == "queued"
        assert db.get(SyncJob, reconcile.id).execution_count == 0
        assert db.get(DatasetState, 1).initialization_status == "complete"
    assert collector.calls == 0  # 初始化使用严格采集器，不能走普通宽松采集路径。
    assert worker.step() is True
    with sessions() as db:
        assert db.get(SyncJob, reconcile.id).status == "succeeded"
        assert db.get(SyncJob, reconcile.id).execution_count == 1
    assert collector.calls == 1


def assert_waiting_reconcile_is_idle(sessions):
    worker, collector, jobs, now = pending_worker(sessions)
    job = old_queued_job(sessions, 'reconcile', now-timedelta(minutes=2))
    for _ in range(2):
        assert worker.step() is False
    with sessions() as db:
        row = db.get(SyncJob, job.id)
        assert row.status == "queued"
        assert row.execution_count == 0
        assert row.lease_generation == 0
    assert collector.calls == 0


def assert_initialization_backoff_is_respected(sessions):
    worker, collector, jobs, now = pending_worker(sessions)
    reconcile = old_queued_job(sessions, 'reconcile', now-timedelta(minutes=2))
    initialize = initialization_job(worker, sessions)
    with sessions.begin() as db:
        db.get(SyncJob, initialize.id).lease_expires_at = now+timedelta(hours=1)
    assert worker.step() is False
    with sessions() as db:
        assert db.get(SyncJob, initialize.id).execution_count == 0
        assert db.get(SyncJob, reconcile.id).execution_count == 0
    assert collector.calls == 0


def assert_pending_event_is_idle(sessions):
    worker, collector, _, now = pending_worker(sessions)
    with sessions.begin() as db:
        db.add(EventInbox(event_id="test-await-initialization", event_type="contact.user.updated_v3", object_id="test-user", payload={}, status="queued", received_at=now))
    for _ in range(2):
        assert worker.step() is False
    with sessions() as db:
        assert db.get(EventInbox, "test-await-initialization").status == "queued"
    assert collector.calls == 0


def test_initialization_is_not_starved(sqlite_sessions):
    assert_initialization_is_not_starved(sqlite_sessions)


def test_waiting_reconcile_is_idle(sqlite_sessions):
    assert_waiting_reconcile_is_idle(sqlite_sessions)


def test_initialization_backoff_is_respected(sqlite_sessions):
    assert_initialization_backoff_is_respected(sqlite_sessions)


def test_pending_event_is_idle(sqlite_sessions):
    assert_pending_event_is_idle(sqlite_sessions)
