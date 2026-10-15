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
        connection.execute('PRAGMA foreign_keys=ON')
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


# SQLite 仅验证事务原子性；不代表 MySQL 行锁并发验收。
from sqlalchemy import BigInteger, select
from sqlalchemy.ext.compiler import compiles
from app.capabilities.contracts import AgentContext
from app.capabilities.receipts import ReceiptRepository
from app.persistence.models import ChangeLog, Department, Employee, EmployeeDepartment, EmployeeStore, OperationReceipt, StoreProfile, SystemSetting
from app.stores.domain import StorePatch
from app.stores.service import StoreAdminService

@compiles(BigInteger, 'sqlite')
def capability_sqlite_integer(element, compiler, **kwargs):
    return 'INTEGER'


def seed_store(sessions):
    with sessions.begin() as db:
        db.add(Department(id='a', feishu_department_id='a', name='门店', sync_quality='complete'))
        db.flush()
        db.add(Employee(id='u', feishu_user_id='u', name='员工', primary_department_id='a', sync_quality='complete'))
        db.flush()
        db.add(EmployeeDepartment(employee_id='u', department_id='a', active=True))


def new_receipt(db, key='key'):
    return ReceiptRepository().create(db, AgentContext('ci_agent', 'agent', 'test'), 'store.apply', key, 'a'*64, datetime.now())


@pytest.mark.parametrize('rollback', [False, True])
def test_store_caller_transaction_includes_projection_version_and_exact_audits(rollback):
    sessions, engine = make_sessions()
    seed_store(sessions)
    service = StoreAdminService(sessions)
    try:
        with sessions() as db:
            with db.begin():
                receipt = new_receipt(db)
                preview = service.preview_in_session(db, [StorePatch('a', True)], 7)
                assert preview['affected_employee_count'] == 1
                result = service.apply_in_session(db, [StorePatch('a', True)], 7, 'agent', datetime.now())
                assert (result.dataset_epoch, result.data_version, result.changed_count) == ('epoch', 8, 1)
                assert list(result.audit_ids) == list(db.scalars(select(ChangeLog.id).order_by(ChangeLog.id)))
                assert len(result.audit_ids) == 1
                ReceiptRepository().mark_submitted(db, receipt.operation_id, result.dataset_epoch, result.data_version, {'changed_count': result.changed_count}, list(result.audit_ids), datetime.now())
                if rollback: db.rollback()
        with sessions() as db:
            assert db.get(DatasetState, 1).data_version == (7 if rollback else 8)
            assert len(list(db.scalars(select(OperationReceipt)))) == (0 if rollback else 1)
            assert len(list(db.scalars(select(ChangeLog)))) == (0 if rollback else 1)
            assert (db.get(EmployeeStore, ('u', 'a')) is None) == rollback
            assert (db.get(StoreProfile, 'a') is None) == rollback
        if not rollback:
            assert service.apply([StorePatch('a', True)], 8, 'agent', datetime.now()) == {'data_version': 8, 'changed_count': 0}
    finally: engine.dispose()


from app.persistence.repositories import SqlSyncJobRepository

@pytest.mark.parametrize('action', ['submit', 'retry'])
@pytest.mark.parametrize('rollback', [False, True])
def test_job_acceptance_joins_caller_transaction(action, rollback):
    sessions, engine = make_sessions()
    now = datetime.now()
    repo = SqlSyncJobRepository(sessions)
    try:
        with sessions.begin() as db:
            db.add(SystemSetting(key='task_queue_lock', value='1'))
            if action == 'retry':
                db.add(SyncJob(id='retry-job', type='full', requested_by='a', status='failed', attempt=2, retry_count=1, lease_generation=3, error_code='REMOTE_ERROR', error_detail='Bearer SYNTHETIC_SECRET', finished_at=now, created_at=now, updated_at=now))
        with sessions() as db:
            with db.begin():
                receipt = new_receipt(db)
                if action == 'submit':
                    job, reused = repo.submit_in_session(db, 'full', None, 'agent', now)
                    assert not reused
                    reused_job, reused = repo.submit_in_session(db, 'full', None, 'agent', now)
                    assert reused and reused_job.id == job.id
                else:
                    job = repo.retry_in_session(db, 'retry-job', 'agent', now)
                    assert (job.attempt, job.retry_count, job.lease_generation) == (3, 2, 3)
                    assert job.error_code is None and job.error_detail is None
                ReceiptRepository().mark_accepted(db, receipt.operation_id, job.id, 'epoch', 7, {'job_id': job.id}, now)
                if rollback: db.rollback()
        with sessions() as db:
            assert len(list(db.scalars(select(OperationReceipt)))) == (0 if rollback else 1)
            jobs = list(db.scalars(select(SyncJob)))
            if action == 'submit': assert len(jobs) == (0 if rollback else 1)
            else:
                assert jobs[0].status == ('failed' if rollback else 'queued')
                assert jobs[0].attempt == (2 if rollback else 3)
                assert len(list(db.scalars(select(ChangeLog)))) == (0 if rollback else 1)
        if action == 'submit' and not rollback:
            job, reused = repo.submit('full', None, 'agent', now)
            assert reused and job.status == 'queued'
    finally: engine.dispose()


from datetime import timedelta
from app.sync.collector import Candidate
from app.sync.publisher import Publisher


def running_receipt(sessions, key='key'):
    now = datetime.now()
    with sessions.begin() as db:
        if db.get(SyncJob, 'job') is None:
            db.add(SyncJob(id='job', type='full', requested_by='agent', status='running', lease_generation=1, lease_expires_at=now+timedelta(hours=1), created_at=now, updated_at=now))
        receipt = new_receipt(db, key)
        state = db.get(DatasetState, 1)
        ReceiptRepository().mark_accepted(db, receipt.operation_id, 'job', state.dataset_epoch, state.data_version, {'job_id':'job'}, now)
        return receipt.operation_id


def changed_candidate():
    return Candidate(departments={'a': {'id':'a', 'feishu_department_id':'a', 'parent_id':None, 'name':'新门店', 'status':'active', 'sync_quality':'complete', 'is_virtual_root':False}}, employees={'u': {'id':'u', 'feishu_user_id':'u', 'name':'新员工', 'status':'active', 'primary_department_id':'a', 'sync_quality':'complete', 'department_ids':['a']}})


@pytest.mark.parametrize('mode', ['changed', 'noop', 'partial'])
def test_publisher_receipts_capture_real_version_and_all_job_audits(mode):
    sessions, engine = make_sessions()
    seed_store(sessions)
    with sessions.begin() as db:
        db.add(StoreProfile(department_id='a', is_store=True))
        db.add(ChangeLog(object_type='store', object_id='unrelated', source='admin', actor='other', after_data={}, committed_at=datetime.now()))
    operation_ids = [running_receipt(sessions, key) for key in ['first', 'second']]
    try:
        candidate = changed_candidate() if mode == 'changed' else Candidate(pending=[('employee','ghost')]) if mode == 'partial' else Candidate()
        Publisher(sessions).publish(candidate, 'job', 1)
        with sessions() as db:
            expected_version = 8 if mode == 'changed' else 7
            assert db.get(DatasetState, 1).data_version == expected_version
            audits = list(db.scalars(select(ChangeLog.id).where(ChangeLog.job_id == 'job').order_by(ChangeLog.id)))
            assert len(audits) == (3 if mode == 'changed' else 0)
            for operation_id in operation_ids:
                row = db.get(OperationReceipt, operation_id)
                assert row.status == 'submitted'
                assert (row.committed_epoch, row.committed_version) == ('epoch', expected_version)
                assert row.result_summary['audit_ids'] == audits
                assert row.result_summary['failure_count'] == (1 if mode == 'partial' else 0)
                assert row.error_code is None
            assert db.get(SyncJob, 'job').status == 'succeeded'
            if mode == 'changed': assert db.get(EmployeeStore, ('u','a')).is_primary
    finally: engine.dispose()


@pytest.mark.parametrize('origin,current,initialization,full,expected', [
    ('old', 'epoch', 'complete', False, 'failed'),
    ('pending', 'epoch', 'complete', True, 'failed'),
    ('pending', 'pending', 'pending', True, 'submitted'),
    ('pending', 'pending', 'complete', True, 'failed'),
])
def test_receipt_generation_guard_allows_only_first_initialization(origin, current, initialization, full, expected):
    sessions, engine = make_sessions()
    try:
        with sessions.begin() as db:
            db.get(DatasetState, 1).dataset_epoch = origin
        operation_id = running_receipt(sessions)
        with sessions.begin() as db:
            state = db.get(DatasetState, 1)
            state.dataset_epoch, state.initialization_status = current, initialization
        Publisher(sessions).publish(Candidate(full=full), 'job', 1)
        with sessions() as db:
            row, state = db.get(OperationReceipt, operation_id), db.get(DatasetState, 1)
            assert row.status == expected
            if expected == 'submitted':
                assert state.dataset_epoch != 'pending'
                assert (row.committed_epoch, row.committed_version) == (state.dataset_epoch, 7)
            else:
                assert row.error_code == 'DATASET_CHANGED'
                assert (row.committed_epoch, row.committed_version) == (origin, 7)
            assert db.get(SyncJob, 'job').status == 'succeeded'
    finally: engine.dispose()


@pytest.mark.parametrize('status,error_code', [('succeeded', None), ('failed', 'FEISHU_UNAVAILABLE'), ('failed', 'bad Bearer SYNTHETIC_SECRET')])
def test_repository_terminal_entrypoints_finalize_receipts_without_overwriting_completed(status, error_code):
    sessions, engine = make_sessions()
    operation_id = running_receipt(sessions)
    completed_id = running_receipt(sessions, 'completed')
    now = datetime.now()
    try:
        with sessions.begin() as db:
            db.add(ChangeLog(object_type='sync_job', object_id='job', source='admin', actor='agent', job_id='job', after_data={'status':'queued'}, committed_at=now))
            ReceiptRepository().mark_submitted(db, completed_id, 'epoch', 7, {'changed_count':99}, [900], now)
        repo = SqlSyncJobRepository(sessions)
        if status == 'succeeded': repo.mark_succeeded('job', 1, now)
        else: repo.mark_failed('job', 1, error_code, 'Bearer SYNTHETIC_SECRET', now)
        with sessions() as db:
            row = db.get(OperationReceipt, operation_id)
            assert row.status == ('submitted' if status == 'succeeded' else 'failed')
            assert (row.committed_epoch, row.committed_version) == ('epoch', 7)
            if status == 'failed':
                assert row.error_code == ('FEISHU_UNAVAILABLE' if error_code == 'FEISHU_UNAVAILABLE' else 'SYNC_FAILED')
                assert 'SYNTHETIC_SECRET' not in str(row.result_summary)
            else: assert row.result_summary['audit_ids'] == [1]
            completed = db.get(OperationReceipt, completed_id)
            assert completed.status == 'submitted'
            assert completed.result_summary == {'changed_count':99, 'audit_ids':[900]}
            assert db.get(SyncJob, 'job').status == status
            assert db.get(DatasetState, 1).data_version == 7
    finally: engine.dispose()


from app.persistence.models import SyncStaging

@pytest.mark.parametrize('operation', ['store', 'publish'])
@pytest.mark.parametrize('failure', ['audit', 'receipt', 'projection', 'version'])
def test_business_transaction_rolls_back_on_injected_write_failure(operation, failure):
    sessions, engine = make_sessions()
    seed_store(sessions)
    if operation == 'publish':
        with sessions.begin() as db: db.add(StoreProfile(department_id='a', is_store=True))
        operation_id = running_receipt(sessions)
    model, hook = {
        'audit': (ChangeLog, 'before_insert'), 'receipt': (OperationReceipt, 'before_update'),
        'projection': (EmployeeStore, 'before_insert'), 'version': (DatasetState, 'before_update'),
    }[failure]
    def fail_write(*args): raise RuntimeError('INJECTED_WRITE_FAILURE')
    event.listen(model, hook, fail_write)
    try:
        with pytest.raises(RuntimeError, match='INJECTED_WRITE_FAILURE'):
            if operation == 'publish': Publisher(sessions).publish(changed_candidate(), 'job', 1)
            else:
                with sessions.begin() as db:
                    receipt = new_receipt(db)
                    result = StoreAdminService(sessions).apply_in_session(db, [StorePatch('a', True)], 7, 'agent', datetime.now())
                    ReceiptRepository().mark_submitted(db, receipt.operation_id, result.dataset_epoch, result.data_version, {}, list(result.audit_ids), datetime.now())
    finally: event.remove(model, hook, fail_write)
    try:
        with sessions() as db:
            assert db.get(DatasetState, 1).data_version == 7
            assert list(db.scalars(select(ChangeLog))) == []
            assert list(db.scalars(select(EmployeeStore))) == []
            assert list(db.scalars(select(SyncStaging))) == []
            assert db.get(Department, 'a').name == '门店'
            assert db.get(Employee, 'u').name == '员工'
            if operation == 'publish':
                assert db.get(SyncJob, 'job').status == 'running'
                assert db.get(OperationReceipt, operation_id).status == 'accepted'
            else:
                assert list(db.scalars(select(OperationReceipt))) == []
                assert db.get(StoreProfile, 'a') is None
    finally: engine.dispose()


@pytest.mark.parametrize('terminal', ['succeeded', 'failed'])
def test_terminal_receipt_failure_rolls_back_job_state(terminal):
    sessions, engine = make_sessions()
    operation_id = running_receipt(sessions)
    def fail_write(*args): raise RuntimeError('INJECTED_RECEIPT_FAILURE')
    event.listen(OperationReceipt, 'before_update', fail_write)
    try:
        repo = SqlSyncJobRepository(sessions)
        with pytest.raises(RuntimeError, match='INJECTED_RECEIPT_FAILURE'):
            if terminal == 'succeeded': repo.mark_succeeded('job', 1, datetime.now())
            else: repo.mark_failed('job', 1, 'FEISHU_UNAVAILABLE', 'private detail', datetime.now())
    finally: event.remove(OperationReceipt, 'before_update', fail_write)
    try:
        with sessions() as db:
            job = db.get(SyncJob, 'job')
            assert job.status == 'running' and job.finished_at is None
            assert job.error_code is None and job.lease_expires_at is not None
            assert db.get(OperationReceipt, operation_id).status == 'accepted'
    finally: engine.dispose()


from app.sync.worker import Worker, utcnow


def failing_worker(sessions, attempt, message):
    class FailingCollector:
        def collect(self, *args, **kwargs): raise RuntimeError(message)
    with sessions.begin() as db:
        job = db.get(SyncJob, 'job')
        job.status, job.attempt, job.lease_expires_at = 'queued', attempt, None
        db.add(SystemSetting(key='task_queue_lock', value='1'))
        db.add(SystemSetting(key='reconcile_schedule', value='{"enabled": false}'))
    worker = Worker(sessions, FailingCollector(), owner='worker')
    assert worker.acquire(utcnow())
    return worker


@pytest.mark.parametrize('attempt,message', [(4, 'FEISHU_UNAVAILABLE'), (5, 'FEISHU_UNAVAILABLE'), (5, 'Bearer SYNTHETIC_SECRET')])
def test_worker_collection_failure_finalizes_only_terminal_receipts(attempt, message):
    sessions, engine = make_sessions()
    operation_id = running_receipt(sessions)
    worker = failing_worker(sessions, attempt, message)
    try:
        assert worker.step()
        with sessions() as db:
            row, job = db.get(OperationReceipt, operation_id), db.get(SyncJob, 'job')
            assert row.status == ('accepted' if attempt == 4 else 'failed')
            assert job.status == ('queued' if attempt == 4 else 'failed')
            assert job.attempt == 5
            assert job.retry_count == (1 if attempt == 4 else 0)
            assert (job.lease_expires_at is not None) == (attempt == 4)
            assert (row.committed_epoch, row.committed_version) == ('epoch', 7)
            assert 'SYNTHETIC_SECRET' not in str(row.result_summary)
            if attempt == 5:
                assert row.error_code == ('FEISHU_UNAVAILABLE' if message == 'FEISHU_UNAVAILABLE' else 'SYNC_FAILED')
            assert len(list(db.scalars(select(ChangeLog).where(ChangeLog.job_id == 'job')))) == 1
            assert db.get(DatasetState, 1).data_version == 7
    finally: engine.dispose()


@pytest.mark.parametrize('failure', ['audit', 'receipt'])
def test_worker_terminal_write_failure_rolls_back_failure_and_audit(failure):
    sessions, engine = make_sessions()
    operation_id = running_receipt(sessions)
    worker = failing_worker(sessions, 5, 'FEISHU_UNAVAILABLE')
    model, hook = (ChangeLog, 'before_insert') if failure == 'audit' else (OperationReceipt, 'before_update')
    def fail_write(*args): raise RuntimeError('INJECTED_WORKER_FAILURE')
    event.listen(model, hook, fail_write)
    try:
        with pytest.raises(RuntimeError, match='INJECTED_WORKER_FAILURE'): worker.step()
    finally: event.remove(model, hook, fail_write)
    try:
        with sessions() as db:
            # 认领独立事务已提交；失败终态、错误和审计事务整体撤销。
            job = db.get(SyncJob, 'job')
            assert job.status == 'running' and job.error_code is None
            assert job.finished_at is None and job.lease_expires_at is not None
            assert db.get(OperationReceipt, operation_id).status == 'accepted'
            assert list(db.scalars(select(ChangeLog))) == []
            assert db.get(DatasetState, 1).data_version == 7
    finally: engine.dispose()


def test_first_full_initialization_commits_new_epoch_and_actual_changed_version():
    sessions, engine = make_sessions()
    try:
        with sessions.begin() as db:
            state = db.get(DatasetState, 1)
            state.dataset_epoch, state.data_version, state.initialization_status = 'pending', 0, 'pending'
        operation_id = running_receipt(sessions)
        candidate = changed_candidate()
        candidate.full = True
        Publisher(sessions).publish(candidate, 'job', 1)
        with sessions() as db:
            row, state = db.get(OperationReceipt, operation_id), db.get(DatasetState, 1)
            assert row.status == 'submitted' and row.before_epoch == 'pending'
            assert row.before_version == 0
            assert row.committed_epoch == state.dataset_epoch != 'pending'
            assert row.committed_version == state.data_version == 1
            assert len(row.result_summary['audit_ids']) == 3
    finally: engine.dispose()



def test_retry_caller_session_cannot_requeue_a_job_from_stale_cached_failure():
    sessions, engine = make_sessions()
    now = datetime.now()
    try:
        with sessions.begin() as db:
            db.add(SyncJob(id='job', type='full', requested_by='agent', status='failed', attempt=1, created_at=now, updated_at=now))
        with sessions() as stale:
            cached = stale.get(SyncJob, 'job')
            stale.commit()
            with sessions.begin() as db:
                job = db.get(SyncJob, 'job')
                job.status, job.attempt = 'running', 2
            assert cached.status == 'failed'
            with pytest.raises(ValueError, match='only failed jobs can be retried'):
                SqlSyncJobRepository(sessions).retry_in_session(stale, 'job', 'agent', now)
            stale.rollback()
        with sessions() as db:
            assert db.get(SyncJob, 'job').status == 'running'
            assert db.get(SyncJob, 'job').attempt == 2
            assert list(db.scalars(select(ChangeLog))) == []
    finally: engine.dispose()



def test_store_caller_session_preserves_current_notes_and_complete_batch_audits():
    sessions, engine = make_sessions()
    seed_store(sessions)
    try:
        with sessions.begin() as db:
            db.add(Department(id='b', feishu_department_id='b', name='分店', sync_quality='complete'))
            db.add(StoreProfile(department_id='a', is_store=False, notes='旧备注'))
            db.add(ChangeLog(object_type='store', object_id='unrelated', source='admin', actor='agent', after_data={}, committed_at=datetime.now()))
        with sessions() as stale:
            cached = stale.get(StoreProfile, 'a')
            stale.commit()
            with sessions.begin() as db:
                db.get(StoreProfile, 'a').notes = '当前备注'
                db.get(DatasetState, 1).data_version = 8
            assert cached.notes == '旧备注'
            with stale.begin():
                result = StoreAdminService(sessions).apply_in_session(stale, [StorePatch('a', True), StorePatch('b', True)], 8, 'agent', datetime.now())
                assert (result.data_version, result.changed_count) == (9, 2)
                assert result.audit_ids == (2, 3)
        with sessions() as db:
            assert db.get(StoreProfile, 'a').notes == '当前备注'
            assert db.get(ChangeLog, 2).before_data['notes'] == '当前备注'
            assert db.get(ChangeLog, 2).after_data['notes'] == '当前备注'
    finally: engine.dispose()



def test_store_write_dependency_reads_emit_mysql_current_read_sql():
    """校验 SQL 读类型；SQLite 执行本身不证明 InnoDB Read View 行为。"""
    from sqlalchemy.dialects import mysql
    sessions, engine = make_sessions()
    seed_store(sessions)
    dependencies = {'dataset_state', 'department', 'store_profile', 'store_code_reservation', 'employee_department', 'employee'}
    observed = []
    try:
        with sessions.begin() as db:
            def record(execution):
                if execution.is_select:
                    statement = execution.statement
                    tables = {table.name for table in statement.get_final_froms()}
                    if tables & dependencies:
                        observed.append((tables, str(statement.compile(dialect=mysql.dialect()))))
            event.listen(db, 'do_orm_execute', record)
            StoreAdminService(sessions).apply_in_session(db, [StorePatch('a', True, 'fresh')], 7, 'agent', datetime.now())
        assert set().union(*(tables for tables, _ in observed)) == dependencies
        unsafe = [sorted(tables) for tables, sql in observed if 'FOR UPDATE' not in sql]
        assert unsafe == [], f'写依赖仍有普通一致性读取: {unsafe}'
    finally: engine.dispose()


# Task 4B：通过公开能力验证策略、读取与原子写入。
def facade(sessions, environment="test"):
    from app.capabilities.service import OrganizationCapabilities
    from app.persistence.read_service import SqlReadService
    return OrganizationCapabilities(sessions, SqlReadService(sessions, "test-secret"), StoreAdminService(sessions), SqlSyncJobRepository(sessions), ReceiptRepository(), ObservationService(), environment=environment)


def agent(**values):
    return AgentContext(**{"actor_type":"human_agent", "actor_id":"agent", "environment":"test", **values})


def test_facade_preview_apply_replay_epoch_and_operation_lookup():
    from app.capabilities.errors import OperationConflict, OperationNotFound
    sessions, engine = make_sessions()
    seed_store(sessions)
    try:
        service = facade(sessions)
        preview = service.preview_store_changes(agent(), [StorePatch("a", True)], 7)
        assert preview.operation_id is None and preview.data["data"]["data_version"] == 7
        result = service.apply_store_changes(agent(), [StorePatch("a", True)], 7, "key", expected_epoch="epoch")
        assert result.data["changed_count"] == 1 and result.observation.data_version == 8
        assert set(result.to_dict()) == {"operation_id", "data", "observation", "audit"}
        replay = service.apply_store_changes(agent(), [StorePatch("a", True)], 7, "key", expected_epoch="epoch")
        assert replay.to_dict() == result.to_dict()
        assert service.get_operation(agent(), idempotency_key="key").operation_id == result.operation_id
        assert service.get_operation(agent(), operation_id=result.operation_id).audit["audit_ids"] == (1,)
        with pytest.raises(OperationNotFound): service.get_operation(agent(actor_id="other"), idempotency_key="key")
        with pytest.raises(OperationConflict): service.apply_store_changes(agent(), [StorePatch("a", True, notes=None)], 7, "key", expected_epoch="epoch")
        with sessions.begin() as db:
            db.get(DatasetState, 1).dataset_epoch = "restored"
            db.get(DatasetState, 1).data_version = 7
        with pytest.raises(Exception) as caught: service.apply_store_changes(agent(), [StorePatch("a", True)], 7, "other", expected_epoch="epoch")
        assert caught.value.code == "DATASET_CHANGED"
        historical = service.get_operation(agent(), idempotency_key="key")
        assert historical.observation.execution == "unconfirmed" and historical.observation.fact_quality == "inconsistent"
        assert (historical.observation.dataset_epoch, historical.observation.data_version) == ("epoch", 8)
        with sessions() as db:
            assert len(list(db.scalars(select(ChangeLog)))) == 1
            assert len(list(db.scalars(select(OperationReceipt)))) == 1
    finally: engine.dispose()


@pytest.mark.parametrize("context,environment,error", [
    (agent(environment="production"), "production", "CONFIRMATION_REQUIRED"),
    (agent(environment="production", approved="yes"), "production", "CONFIRMATION_REQUIRED"),
    (agent(actor_type="ci_agent", environment="production", approved=True, run_id="test-a"), "production", "CAPABILITY_NOT_ALLOWED"),
    (agent(actor_type="ci_agent", run_id="run-a"), "test", "CAPABILITY_NOT_ALLOWED"),
    (agent(), "production", "CAPABILITY_NOT_ALLOWED"),
])
def test_facade_policy_denies_before_any_write(context, environment, error):
    sessions, engine = make_sessions()
    try:
        with pytest.raises(Exception) as caught:
            facade(sessions, environment).apply_store_changes(context, [StorePatch("a", True)], 7, "key", "arbitrary-token", expected_epoch="epoch")
        assert caught.value.code == error
        with sessions() as db: assert list(db.scalars(select(OperationReceipt))) == []
    finally: engine.dispose()


def test_facade_ci_memory_and_production_confirmation():
    sessions, engine = make_sessions()
    seed_store(sessions)
    try:
        result = facade(sessions).apply_store_changes(agent(actor_type="ci_agent", run_id="test-run"), [StorePatch("a", True)], 7, "key", expected_epoch="epoch")
        assert result.observation.execution == "submitted"
        assert facade(sessions, "production").status(agent(environment="production")).operation_id is None
    finally: engine.dispose()


def test_facade_read_pagination_ambiguity_and_target_quality():
    sessions, engine = make_sessions()
    seed_store(sessions)
    try:
        with sessions.begin() as db:
            db.get(DatasetState, 1).coverage_status = "complete"
            db.get(Department, "a").sync_quality = "pending_verification"
            db.add_all([Department(id=f"x{i:03}", feishu_department_id=f"x{i:03}", name="重名", sync_quality="complete") for i in range(505)])
        service = facade(sessions)
        for result in [service.status(agent()), service.get_department(agent(), "a"), service.list_employees(agent(), limit=1), service.get_employee(agent(), "u"), service.list_stores(agent()), service.get_store(agent(), "a"), service.list_store_employees(agent(), "a")]:
            assert result.observation.data_version == result.data["meta"]["data_version"] == 7
            assert result.operation_id is None and result.observation.execution != "verified"
        assert service.get_department(agent(), "a").observation.fact_quality == "unknown"
        with pytest.raises(Exception) as caught: service.find_departments(agent(), name="重名")
        assert caught.value.code == "AMBIGUOUS_TARGET" and len(caught.value.candidates) == 505
        by_id = service.find_departments(agent(), department_id="x504")
        assert by_id.data["data"][0]["id"] == "x504"
        first = service.find_departments(agent(), limit=1)
        assert first.data["meta"]["next_cursor"]
        with pytest.raises(Exception) as caught: service.find_departments(agent(), path=["重名"])
        assert caught.value.code == "AMBIGUOUS_TARGET"
    finally: engine.dispose()


def test_facade_sync_reuse_retry_and_safe_evidence():
    sessions, engine = make_sessions()
    seed_store(sessions)
    try:
        with sessions.begin() as db: db.add(SystemSetting(key="task_queue_lock", value="1"))
        service = facade(sessions)
        one = service.request_sync(agent(), "full", "sync-1")
        two = service.request_sync(agent(), "full", "sync-2")
        assert one.data["job_id"] == two.data["job_id"] and one.observation.execution == "accepted"
        with sessions.begin() as db:
            job = db.get(SyncJob, one.data["job_id"])
            job.status, job.error_detail, job.error_code = "failed", "Bearer SYNTHETIC_SECRET", "BAD secret"
            db.add(SyncJobDetail(id=1, job_id=job.id, object_type="employee", object_id="u", status="failed", error_message="Bearer SYNTHETIC_SECRET"))
        safe = service.get_sync_job(agent(), one.data["job_id"])
        assert "SYNTHETIC_SECRET" not in str(safe.to_dict()) and safe.observation.execution == "failed"
        retried = service.retry_sync_job(agent(), one.data["job_id"], "retry")
        assert retried.observation.execution == "accepted"
        assert service.retry_sync_job(agent(), one.data["job_id"], "retry").operation_id == retried.operation_id
        with pytest.raises(Exception): service.request_sync(agent(), "full", "bad", root_department_id="a")
        with pytest.raises(Exception): service.request_sync(agent(), "subtree", "bad-subtree")
    finally: engine.dispose()


@pytest.mark.parametrize("failure", ["receipt", "audit"])
def test_facade_atomic_store_failure_rolls_back_everything(failure):
    from app.capabilities.errors import CapabilityUnavailable
    sessions, engine = make_sessions()
    seed_store(sessions)
    model, hook = (OperationReceipt, "before_update") if failure == "receipt" else (ChangeLog, "before_insert")
    def injected(*args): raise RuntimeError("Bearer SYNTHETIC_SECRET")
    event.listen(model, hook, injected)
    try:
        with pytest.raises(CapabilityUnavailable) as caught:
            facade(sessions).apply_store_changes(agent(), [StorePatch("a", True)], 7, "rollback", expected_epoch="epoch")
        assert "SYNTHETIC_SECRET" not in str(caught.value.to_dict())
    finally: event.remove(model, hook, injected)
    try:
        with sessions() as db:
            assert list(db.scalars(select(OperationReceipt))) == []
            assert list(db.scalars(select(ChangeLog))) == []
            assert list(db.scalars(select(EmployeeStore))) == []
            assert db.get(StoreProfile, "a") is None
            assert db.get(DatasetState, 1).data_version == 7
    finally: engine.dispose()


def test_facade_ci_checks_actual_bind_not_declared_environment(tmp_path):
    from app.capabilities.errors import CapabilityNotAllowed
    sessions, engine = make_sessions()
    other_engine = create_engine("sqlite:///" + str(tmp_path / "unit.db"))
    try:
        other_sessions = sessionmaker(other_engine)
        with pytest.raises(CapabilityNotAllowed): facade(other_sessions).status(agent(actor_type="ci_agent", run_id="test-a"))
        from unittest.mock import Mock
        from sqlalchemy.engine import make_url
        service = facade(sessions)
        for url, actual, permitted in [
            ("mysql+pymysql://localhost/unit_test", "unit_test", True),
            ("mysql+pymysql://localhost/production", "production", False),
            ("mysql+mysqldb://localhost/unit_test", "unit_test", False),
            ("mysql+pymysql://localhost/unit_test", "production", False),
        ]:
            db = Mock()
            db.get_bind.return_value.engine.url = make_url(url)
            db.scalar.return_value = actual
            if permitted: service._bind_policy(db, agent(actor_type="ci_agent", run_id="test-a"))
            else:
                with pytest.raises(CapabilityNotAllowed): service._bind_policy(db, agent(actor_type="ci_agent", run_id="test-a"))
    finally:
        engine.dispose()
        other_engine.dispose()


def test_facade_read_snapshot_uses_one_session_and_target_quality():
    sessions, engine = make_sessions()
    seed_store(sessions)
    try:
        with sessions.begin() as db:
            db.get(DatasetState, 1).coverage_status = "complete"
            db.get(Employee, "u").primary_store_status = "inconsistent"
            db.add(StoreProfile(department_id="a", is_store=True))
        service = facade(sessions)
        assert service.get_employee(agent(), "u").observation.fact_quality == "inconsistent"
        observed = []
        original = service.reads.get_department_in_session
        def capture(db, department_id):
            observed.append(db)
            return original(db, department_id)
        service.reads.get_department_in_session = capture
        base = service.observations._base
        def capture_obs(db, *args, **kwargs):
            assert observed == [db]
            return base(db, *args, **kwargs)
        service.observations._base = capture_obs
        assert service.get_department(agent(), "a").data["meta"]["data_version"] == 7
        service.observations._base = base
        with sessions.begin() as db: db.get(DatasetState, 1).initialization_status = "pending"
        unknown = service.status(agent())
        assert unknown.data["data"] is None and unknown.observation.fact_quality == "unknown"
    finally: engine.dispose()


def test_facade_logs_paginate_filter_and_drop_credential_payloads():
    sessions, engine = make_sessions()
    try:
        with sessions.begin() as db:
            for identifier, object_type in [(1,"store"), (2,"store"), (3,"api_client")]:
                db.add(ChangeLog(id=identifier, object_type=object_type, object_id="a", source="admin", actor="agent", before_data=None, after_data={"status":"active", "notes":"Bearer SYNTHETIC_SECRET", "password":"SYNTHETIC_SECRET"}, committed_at=datetime.now()))
        service = facade(sessions)
        result = service.get_change_logs(agent(), object_id="a", action="create", limit=1)
        assert result.data["data"][0]["id"] == 2 and result.data["meta"]["next_cursor"] != "2"
        assert "SYNTHETIC_SECRET" not in str(result.to_dict())
        next_page = service.get_change_logs(agent(), object_id="a", action="create", cursor=result.data["meta"]["next_cursor"], limit=1)
        assert next_page.data["data"][0]["id"] == 1 and next_page.data["meta"]["next_cursor"] is None
    finally: engine.dispose()


def test_facade_unknown_operation_and_history_never_mutate_receipt():
    from app.capabilities.errors import InvalidCapabilityRequest
    sessions, engine = make_sessions()
    try:
        with sessions.begin() as db:
            receipt = new_receipt(db)
            receipt.status = "future_status"
            operation_id = receipt.operation_id
        result = facade(sessions).get_operation(agent(), operation_id=operation_id)
        assert result.observation.execution == "unconfirmed" and result.observation.fact_quality == "unknown"
        with pytest.raises(InvalidCapabilityRequest): facade(sessions).get_operation(agent())
        with sessions() as db: assert db.get(OperationReceipt, operation_id).status == "future_status"
    finally: engine.dispose()


def test_facade_runtime_and_settings_wiring(monkeypatch):
    from app import dependencies
    from app.config import Settings
    from pydantic import ValidationError
    from app.capabilities.service import OrganizationCapabilities
    sessions, engine = make_sessions()
    try:
        settings = Settings(database_url="mysql+pymysql://localhost/unit_test", session_secret="unit-secret", agent_environment="test")
        monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
        monkeypatch.setattr(dependencies, "create_mysql_engine", lambda url: engine)
        monkeypatch.setattr(dependencies, "session_factory", lambda bind: sessions)
        dependencies.get_runtime.cache_clear()
        runtime = dependencies.get_runtime()
        assert isinstance(runtime.capabilities, OrganizationCapabilities)
        assert runtime.capabilities.reads is runtime.reads and runtime.capabilities.jobs is runtime.jobs
        assert runtime.capabilities.environment == "test"
        with pytest.raises(ValidationError): Settings(agent_environment="staging")
        from app.persistence.database import create_mysql_engine
        with pytest.raises(ValueError): create_mysql_engine("sqlite://")
    finally:
        dependencies.get_runtime.cache_clear()
        engine.dispose()


@pytest.mark.parametrize("target_quality", ["unknown", "pending_verification", "inconsistent"])
def test_facade_store_quality_and_empty_members_keep_target_uncertainty(target_quality):
    sessions, engine = make_sessions()
    seed_store(sessions)
    try:
        with sessions.begin() as db:
            db.get(DatasetState, 1).coverage_status = "complete"
            db.get(Department, "a").sync_quality = target_quality
            db.add(StoreProfile(department_id="a", is_store=True))
        service = facade(sessions)
        expected = "inconsistent" if target_quality == "inconsistent" else "unknown"
        assert service.get_store(agent(), "a").observation.fact_quality == expected
        assert service.list_stores(agent()).observation.fact_quality == expected
        assert service.list_store_employees(agent(), "a").observation.fact_quality == expected
    finally: engine.dispose()


@pytest.mark.parametrize("action", ["submit", "retry"])
def test_facade_sync_receipt_failure_rolls_back_job_and_audit(action):
    from app.capabilities.errors import CapabilityUnavailable
    sessions, engine = make_sessions()
    now = datetime.now()
    with sessions.begin() as db:
        db.add(SystemSetting(key="task_queue_lock", value="1"))
        if action == "retry": db.add(SyncJob(id="failed", type="full", requested_by="old", status="failed", attempt=1, created_at=now, updated_at=now))
    def fail(*args): raise RuntimeError("INJECTED_RECEIPT_FAILURE")
    event.listen(OperationReceipt, "before_update", fail)
    try:
        service = facade(sessions)
        with pytest.raises(CapabilityUnavailable):
            if action == "submit": service.request_sync(agent(), "full", "atomic")
            else: service.retry_sync_job(agent(), "failed", "atomic")
    finally: event.remove(OperationReceipt, "before_update", fail)
    try:
        with sessions() as db:
            assert list(db.scalars(select(OperationReceipt))) == []
            assert list(db.scalars(select(ChangeLog))) == []
            if action == "submit": assert list(db.scalars(select(SyncJob))) == []
            else:
                job = db.get(SyncJob, "failed")
                assert job.status == "failed" and job.attempt == 1 and job.requested_by == "old"
    finally: engine.dispose()


def test_facade_confirmation_success_missing_epoch_and_normalized_idempotency():
    from app.capabilities.errors import InvalidCapabilityRequest
    sessions, engine = make_sessions()
    seed_store(sessions)
    try:
        service = facade(sessions, "production")
        context = agent(environment="production", approved=True)
        with pytest.raises(InvalidCapabilityRequest): service.apply_store_changes(context, [StorePatch("a", True)], 7, "missing")
        result = service.apply_store_changes(context, [StorePatch("a", True, " code ")], 7, "key", expected_epoch="epoch")
        replay = service.apply_store_changes(context, [StorePatch("a", True, "code")], 7, "key", expected_epoch="epoch")
        assert result.to_dict() == replay.to_dict()
        with sessions() as db: assert db.get(StoreProfile, "a").store_code == "code"
    finally: engine.dispose()



def test_facade_operation_keeps_receipt_status_and_complete_async_audits():
    sessions, engine = make_sessions()
    operation_id = running_receipt(sessions)
    try:
        with sessions.begin() as db:
            db.add(ChangeLog(object_type="sync_job", object_id="job", source="admin", actor="agent", job_id="job", after_data={"status":"queued"}, committed_at=datetime.now()))
        service = facade(sessions)
        running = service.get_operation(agent(), operation_id=operation_id)
        assert running.observation.execution == "running" and running.audit["audit_ids"] == (1,)
        SqlSyncJobRepository(sessions).mark_succeeded("job", 1, datetime.now())
        submitted = service.get_operation(agent(), operation_id=operation_id)
        assert submitted.data["status"] == "submitted"
        assert submitted.data["summary"]["status"] == "succeeded"
        assert submitted.observation.execution == "submitted" and submitted.audit["audit_ids"] == (1,)
    finally: engine.dispose()


# Review round 1: bind Agent audit pagination to its observation snapshot.
@pytest.mark.parametrize("change", ["epoch", "version", "expected_epoch", "expected_version", "filters"])
def test_review_i1_log_cursor_rejects_dataset_or_filter_change(change):
    sessions, engine = make_sessions()
    try:
        with sessions.begin() as db:
            for identifier in (1, 2):
                db.add(ChangeLog(id=identifier, object_type="store", object_id="a", source="admin", actor="agent", after_data={"is_store":True}, committed_at=datetime(2026, 1, identifier)))
        service = facade(sessions)
        first = service.get_change_logs(agent(), object_id="a", limit=1)
        filters = {"object_id":"a", "limit":1, "cursor":first.data["meta"]["next_cursor"]}
        if change in {"epoch", "version"}:
            with sessions.begin() as db:
                state = db.get(DatasetState, 1)
                if change == "epoch": state.dataset_epoch = "restored"
                else: state.data_version += 1
        elif change == "expected_epoch": filters["dataset_epoch"] = "old"
        elif change == "expected_version": filters["data_version"] = 6
        else: filters["object_id"] = "b"
        with pytest.raises(Exception) as caught: service.get_change_logs(agent(), **filters)
        assert caught.value.code == ("INVALID_CURSOR" if change == "filters" else "DATASET_CHANGED")
    finally: engine.dispose()


def test_review_i1_time_filters_normalize_for_signed_log_cursor():
    from datetime import timezone, timedelta
    sessions, engine = make_sessions()
    try:
        with sessions.begin() as db:
            for identifier in (1, 2, 3):
                db.add(ChangeLog(id=identifier, object_type="store", object_id="a", source="admin", actor="agent", after_data={"is_store":True}, committed_at=datetime(2026, 1, identifier)))
        service = facade(sessions)
        after = datetime(2026, 1, 1, tzinfo=timezone.utc)
        before = datetime(2026, 1, 2, 23, tzinfo=timezone.utc)
        first = service.get_change_logs(agent(), committed_after=after, committed_before=before, limit=1)
        cursor = first.data["meta"]["next_cursor"]
        assert first.data["data"][0]["id"] == 2 and cursor != "2"
        tz = timezone(timedelta(hours=8))
        second = service.get_change_logs(agent(), committed_after=after.astimezone(tz), committed_before=before.astimezone(tz), limit=1, cursor=cursor)
        assert second.data["data"][0]["id"] == 1 and second.data["meta"]["next_cursor"] is None
        with pytest.raises(Exception) as caught:
            service.get_change_logs(agent(), committed_after=after + timedelta(seconds=1), committed_before=before, limit=1, cursor=cursor)
        assert caught.value.code == "INVALID_CURSOR"
        with pytest.raises(Exception) as caught:
            service.get_change_logs(agent(), committed_after=datetime(2026, 1, 1), limit=1)
        assert caught.value.code == "INVALID_CAPABILITY_REQUEST"
    finally: engine.dispose()


@pytest.mark.parametrize("target", ["missing", "department_only", "non_store", "inactive", "empty"])
def test_review_i2_store_members_distinguish_invalid_target_from_empty_store(target):
    sessions, engine = make_sessions()
    try:
        with sessions.begin() as db:
            db.get(DatasetState, 1).coverage_status = "complete"
            if target != "missing":
                db.add(Department(id="shop", feishu_department_id="shop", name="shop", status="inactive" if target == "inactive" else "active", sync_quality="complete"))
                if target != "department_only": db.add(StoreProfile(department_id="shop", is_store=target != "non_store"))
        result = facade(sessions).list_store_employees(agent(), "shop")
        if target == "empty":
            assert result.data["data"] == () and result.observation.fact_quality == "resolved"
        else:
            assert result.data["data"] is None
            assert result.observation.execution == "unconfirmed" and result.observation.fact_quality == "unknown"
            assert result.observation.evidence["target_status"] in {"missing", "not_store", "inactive"}
        assert result.data["meta"]["data_version"] == result.observation.data_version == 7
    finally: engine.dispose()


def test_review_i3_failed_operation_audits_survive_later_retry():
    sessions, engine = make_sessions()
    operation_id = running_receipt(sessions)
    try:
        with sessions.begin() as db:
            db.add(ChangeLog(object_type="sync_job", object_id="job", source="admin", actor="agent", job_id="job", after_data={"status":"running"}, committed_at=datetime.now()))
        SqlSyncJobRepository(sessions).mark_failed("job", 1, "SYNC_FAILED", "Bearer SYNTHETIC_SECRET", datetime.now())
        service = facade(sessions)
        failed = service.get_operation(agent(), operation_id=operation_id)
        assert failed.audit["audit_ids"] == (1,) and failed.data["status"] == "failed"
        service.retry_sync_job(agent(), "job", "later-retry")
        historical = service.get_operation(agent(), operation_id=operation_id)
        assert historical.audit["audit_ids"] == (1,) and historical.data["status"] == "failed"
        assert "SYNTHETIC_SECRET" not in str(historical.to_dict())
    finally: engine.dispose()


@pytest.mark.parametrize("expected", [{"dataset_epoch":"old"}, {"data_version":6}])
def test_review_i1_explicit_dataset_expectation_applies_to_first_page(expected):
    sessions, engine = make_sessions()
    try:
        with pytest.raises(Exception) as caught: facade(sessions).get_change_logs(agent(), **expected)
        assert caught.value.code == "DATASET_CHANGED" and caught.value.status == 409
    finally: engine.dispose()
