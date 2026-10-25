"""初始化前的真实 Worker 队列回归；不能被较早的核对任务饿死。"""
from datetime import timedelta

from app.persistence.models import DatasetState, EventInbox, SyncJob, WorkerLease
from app.persistence.repositories import SqlSyncJobRepository
from app.sync.collector import Candidate
from app.sync.worker import Worker, utcnow


class CountingCollector:
    def __init__(self):
        self.calls = 0

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
    worker = Worker(sessions, collector, owner="test-initialization-queue")
    assert worker.acquire(now)
    jobs = SqlSyncJobRepository(sessions)
    return worker, collector, jobs, now


def assert_initialization_is_not_starved(sessions):
    worker, collector, jobs, now = pending_worker(sessions)
    reconcile, _ = jobs.submit("reconcile", None, "listener", now-timedelta(minutes=2))
    initialize, _ = jobs.submit("initialize", None, "test", now-timedelta(minutes=1))
    assert worker.step() is True
    with sessions() as db:
        assert db.get(SyncJob, initialize.id).status == "succeeded"
        assert db.get(SyncJob, reconcile.id).status == "queued"
        assert db.get(SyncJob, reconcile.id).execution_count == 0
        assert db.get(DatasetState, 1).initialization_status == "complete"
    assert collector.calls == 1
    assert worker.step() is True
    with sessions() as db:
        assert db.get(SyncJob, reconcile.id).status == "succeeded"
        assert db.get(SyncJob, reconcile.id).execution_count == 1
    assert collector.calls == 2


def assert_waiting_reconcile_is_idle(sessions):
    worker, collector, jobs, now = pending_worker(sessions)
    job, _ = jobs.submit("reconcile", None, "listener", now-timedelta(minutes=2))
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
    reconcile, _ = jobs.submit("reconcile", None, "listener", now-timedelta(minutes=2))
    initialize, _ = jobs.submit("initialize", None, "test", now-timedelta(minutes=1))
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
