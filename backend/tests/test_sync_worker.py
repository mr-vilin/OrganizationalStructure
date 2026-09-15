from datetime import datetime, timedelta
import pytest
from test_sync_persistence import sessions
from app.persistence.models import WorkerLease, SyncJob, EventInbox, DatasetState


def test_single_worker_lease_fences_old_owner_and_recovers_expired_job(sessions):
    from app.sync.worker import Worker
    now = datetime(2026,9,15)
    with sessions.begin() as db:
        db.add(WorkerLease(id=1, generation=0))
        db.add(SyncJob(id='j', type='full', requested_by='test', status='running', lease_generation=1, lease_expires_at=now-timedelta(seconds=1), created_at=now, updated_at=now))
    a, b = Worker(sessions, None, owner='a'), Worker(sessions, None, owner='b')
    assert a.acquire(now) is True
    assert b.acquire(now) is False
    assert b.acquire(now+timedelta(minutes=3)) is True
    assert a.renew(now+timedelta(minutes=3)) is False
    b.recover(now+timedelta(minutes=3))
    with sessions() as db:
        job=db.get(SyncJob,'j')
        assert job.status == 'queued' and job.lease_generation == 2


def test_worker_failed_collection_does_not_publish_version(sessions):
    from app.sync.worker import Worker, utcnow
    from app.persistence.repositories import SqlSyncJobRepository
    class Collector:
        def collect(self, root=None, **kwargs): raise RuntimeError('FEISHU_API_ERROR')
    with sessions.begin() as db: db.add(WorkerLease(id=1, generation=0))
    job,_=SqlSyncJobRepository(sessions).submit('full', None, 'test', utcnow())
    worker=Worker(sessions, Collector())
    assert worker.acquire(utcnow())
    worker.step()
    with sessions() as db:
        assert db.get(DatasetState,1).data_version == 1
        job=db.get(SyncJob,job.id)
        assert job.error_code == 'FEISHU_API_ERROR'
        assert job.status == 'queued' and job.lease_expires_at > utcnow()


def test_stale_worker_cannot_rewrite_processed_event(sessions):
    from app.sync.worker import Worker, utcnow
    with sessions.begin() as db:
        db.add(WorkerLease(id=1,owner='new',generation=2,expires_at=utcnow()+timedelta(minutes=1)))
        db.add(EventInbox(event_id='e',event_type='contact.user.updated_v3',object_id='u',payload={},status='succeeded',received_at=utcnow()))
    old=Worker(sessions,None,owner='old'); old.generation=1
    old._fail_event('e')
    with sessions() as db: assert db.get(EventInbox,'e').status=='succeeded'
