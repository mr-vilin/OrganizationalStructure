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



