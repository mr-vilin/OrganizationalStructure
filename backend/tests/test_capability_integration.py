from datetime import datetime
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.capabilities.observations import ObservationService
from app.persistence.models import Base, DatasetState, SyncJob, SyncJobDetail, PendingFact

def make_sessions():
    engine=create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def configure(connection, _):
        connection.create_collation('utf8mb4_bin', lambda a, b: (a > b) - (a < b))
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(DatasetState(id=1,dataset_epoch='epoch',data_version=7,initialization_status='complete'))
    return factory, engine

def test_observation_job_mapping_and_partial():
    sessions, engine = make_sessions()
    with sessions.begin() as db:
        db.add(SyncJob(id='job', type='full', requested_by='a', status='succeeded', created_at=datetime.now(), updated_at=datetime.now()))
    service=ObservationService()
    with sessions() as db:
        obs=service.observation_for_job(db,'job')
        assert obs.execution == 'submitted' and obs.data_version == 7
    with sessions.begin() as db:
        db.add(SyncJobDetail(id=1, job_id='job', object_type='department', object_id='x', status='failed', error_code='E'))
    with sessions() as db:
        assert service.observation_for_job(db,'job').execution == 'partial'
    engine.dispose()

def test_observation_pending_and_unconfirmed():
    sessions, engine=make_sessions(); service=ObservationService()
    with sessions.begin() as db:
        db.add(SyncJob(id='job',type='full',requested_by='a',status='succeeded',created_at=datetime.now(),updated_at=datetime.now()))
        db.add(PendingFact(object_type='department',source_id='x',normalized_data={},error_code='PENDING',updated_at=datetime.now()))
    with sessions() as db:
        obs=service.observation_for_job(db,'job')
        assert obs.execution=='partial' and obs.fact_quality=='partial'
        assert service.observation_for_status(db, 'queued').execution == 'accepted'
    engine.dispose()




import pytest

@pytest.mark.parametrize('status,execution', [('queued','accepted'), ('running','running'), ('succeeded','submitted'), ('failed','failed')])
def test_all_job_statuses(status, execution):
    sessions, engine = make_sessions()
    try:
        with sessions.begin() as db:
            db.add(SyncJob(id='job', type='full', requested_by='a', status=status, created_at=datetime.now(), updated_at=datetime.now()))
        with sessions() as db:
            obs = ObservationService().observation_for_job(db, 'job')
            assert obs.execution == execution
            assert (obs.dataset_epoch, obs.data_version) == ('epoch', 7)
    finally: engine.dispose()

@pytest.mark.parametrize('initialization,coverage,quality', [
    ('pending','unknown','unknown'), ('complete','unknown','unknown'),
    ('complete','incomplete','partial'), ('complete','complete','resolved'),
])
def test_observation_quality_respects_dataset_coverage(initialization, coverage, quality):
    sessions, engine = make_sessions()
    try:
        with sessions.begin() as db:
            state = db.get(DatasetState, 1)
            state.initialization_status, state.coverage_status = initialization, coverage
        with sessions() as db:
            service = ObservationService()
            assert service.observation_for_status(db, 'queued').fact_quality == quality
            assert service.observation_for_commit(db, 'epoch', 7).fact_quality == quality
    finally: engine.dispose()


def test_unavailable_missing_and_unknown_observations():
    from unittest.mock import Mock
    service = ObservationService(); unavailable = Mock()
    unavailable.scalar.side_effect = RuntimeError('Bearer SYNTHETIC_SECRET')
    unavailable.execute.side_effect = RuntimeError('Bearer SYNTHETIC_SECRET')
    unavailable.get.side_effect = RuntimeError('Bearer SYNTHETIC_SECRET')
    for obs in [service.observation_for_status(unavailable, 'queued'), service.observation_for_job(unavailable, 'job'), service.observation_for_commit(unavailable, 'epoch', 7)]:
        assert obs.execution == 'unconfirmed' and obs.fact_quality == 'unknown'
        assert 'SYNTHETIC_SECRET' not in str(obs.to_dict())
    sessions, engine = make_sessions()
    try:
        with sessions() as db:
            assert service.observation_for_job(db, 'missing').execution == 'unconfirmed'
            assert service.observation_for_status(db, 'not-a-status').execution == 'unconfirmed'
        with sessions.begin() as db: db.delete(db.get(DatasetState, 1))
        with sessions() as db: assert service.observation_for_status(db, 'queued').execution == 'unconfirmed'
    finally: engine.dispose()

@pytest.mark.parametrize('epoch,version', [('old',7), ('epoch',6)])
def test_commit_expected_dataset_mismatch(epoch, version):
    sessions, engine = make_sessions()
    try:
        with sessions() as db:
            obs = ObservationService().observation_for_commit(db, epoch, version)
            assert obs.execution == 'unconfirmed' and obs.fact_quality == 'inconsistent'
            assert (obs.dataset_epoch, obs.data_version) == ('epoch', 7)
    finally: engine.dispose()

def test_commit_observation_uses_job_partial_and_one_fresh_dataset_pair():
    sessions, engine = make_sessions()
    try:
        with sessions.begin() as db:
            db.add(SyncJob(id='job', type='full', requested_by='a', status='succeeded', created_at=datetime.now(), updated_at=datetime.now()))
            db.add(SyncJobDetail(id=1, job_id='job', object_type='department', object_id='x', status='failed'))
        with sessions() as db:
            cached = db.get(DatasetState, 1)
            db.commit()
            with sessions.begin() as writer:
                state = writer.get(DatasetState, 1)
                state.dataset_epoch, state.data_version = 'new-epoch', 12
            assert (cached.dataset_epoch, cached.data_version) == ('epoch', 7)
            obs = ObservationService().observation_for_commit(db, 'new-epoch', 12, 'job')
            assert obs.execution == 'partial' and obs.fact_quality == 'partial'
            assert (obs.dataset_epoch, obs.data_version) == ('new-epoch', 12)
    finally: engine.dispose()
