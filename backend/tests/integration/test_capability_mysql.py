"""独立 MySQL 8.4 双事务验收；不使用单连接 savepoint 夹具。"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, or_, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.persistence.database import create_mysql_engine
from app.capabilities import AgentContext, CapabilityError, CapabilityUnavailable, DatasetChangedError, OrganizationCapabilities
from app.capabilities.observations import ObservationService
from app.capabilities.receipts import ReceiptRepository
from app.persistence.models import ChangeLog, DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, OperationReceipt, StoreCodeReservation, StoreProfile, SyncJob, SyncJobDetail, SyncStaging
from app.persistence.read_service import SqlReadService
from app.persistence.repositories import SqlSyncJobRepository
from app.stores.domain import InvalidStoreChanges, StorePatch
from app.stores.service import StoreAdminService
from app.sync.collector import Candidate
from app.sync.publisher import Publisher


@pytest.fixture
def independent_capability_mysql():
    url = os.environ.get('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('未提供 ORG_TEST_DATABASE_URL；MySQL 双事务旧快照验收未执行')
    parsed = make_url(url)
    if parsed.drivername != 'mysql+pymysql' or not (parsed.database or '').endswith('_test'):
        pytest.fail('仅允许 mysql+pymysql 且数据库名以 _test 结尾的独立测试库')
    engine = create_mysql_engine(url)
    sessions = sessionmaker(engine, expire_on_commit=False)
    prefix = 'cap_rr_' + uuid4().hex
    ids = {name: prefix + '_' + name for name in ['shop', 'other', 'leaf', 'u', 'w', 'new']}
    original = None
    try:
        with sessions.begin() as db:
            assert db.scalar(text('SELECT VERSION()')).startswith('8.4.'), '本用例要求 MySQL 8.4'
            assert db.scalar(text('SELECT @@transaction_isolation')) == 'REPEATABLE-READ'
            # 重建投影会触及整个数据集；要求专用测试库没有其它组织事实。
            assert db.scalar(select(func.count()).select_from(Department)) == 0, '请使用没有组织事实的独立 _test 库'
            assert db.scalar(select(func.count()).select_from(Employee)) == 0, '请使用没有组织事实的独立 _test 库'
            assert db.scalar(select(func.count()).select_from(SyncJob)) == 0, '请使用没有同步任务的独立 _test 库'
            state = db.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
            assert state is not None, '请先执行现有 alembic upgrade head'
            original = {column.name: getattr(state, column.name) for column in DatasetState.__table__.columns if column.name != 'id'}
            state.dataset_epoch, state.data_version, state.initialization_status = prefix, 7, 'complete'
            state.coverage_status = 'complete'
            db.add_all([Department(id=ids[key], feishu_department_id=ids[key], name=key, status='active', sync_quality='complete') for key in ['shop', 'other']])
            db.flush()
            db.add(Department(id=ids['leaf'], feishu_department_id=ids['leaf'], parent_id=ids['shop'], name='leaf', status='active', sync_quality='complete'))
            db.add(StoreProfile(department_id=ids['shop'], is_store=False, notes='old-notes'))
            db.add(StoreProfile(department_id=ids['other'], is_store=False))
            db.flush()
            for key in ['u', 'w']:
                db.add(Employee(id=ids[key], feishu_user_id=ids[key], name=key, primary_department_id=ids['leaf'], status='active', sync_quality='complete'))
            db.flush()
            for key in ['u', 'w']:
                db.add(EmployeeDepartment(employee_id=ids[key], department_id=ids['leaf'], active=True, is_primary=True))
        yield sessions, ids, prefix
    finally:
        if original is not None:
            with sessions.begin() as db:
                state = db.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
                job_ids = list(db.scalars(select(SyncJob.id).where(SyncJob.requested_by == prefix)))
                db.execute(delete(OperationReceipt).where(OperationReceipt.actor_id == prefix))
                db.execute(delete(ChangeLog).where(or_(ChangeLog.actor == prefix, ChangeLog.job_id.in_(job_ids))))
                db.execute(delete(SyncStaging).where(SyncStaging.job_id.in_(job_ids)))
                db.execute(delete(SyncJobDetail).where(SyncJobDetail.job_id.in_(job_ids)))
                db.execute(delete(SyncJob).where(SyncJob.id.in_(job_ids)))
                db.execute(delete(EmployeeStore).where(EmployeeStore.employee_id.in_([ids[k] for k in ['u', 'w', 'new']])))
                db.execute(delete(EmployeeDepartment).where(EmployeeDepartment.employee_id.in_([ids[k] for k in ['u', 'w', 'new']])))
                db.execute(delete(Employee).where(Employee.id.in_([ids[k] for k in ['u', 'w', 'new']])))
                db.execute(delete(StoreCodeReservation).where(StoreCodeReservation.department_id.in_([ids['shop'], ids['other']])))
                db.execute(delete(StoreProfile).where(StoreProfile.department_id.in_([ids['shop'], ids['other']])))
                db.execute(delete(Department).where(Department.id == ids['leaf']))
                db.execute(delete(Department).where(Department.id.in_([ids['shop'], ids['other']])))
                for key, value in original.items(): setattr(state, key, value)
        engine.dispose()


def test_borrowed_rr_uses_current_notes_and_all_projection_dependencies(independent_capability_mysql):
    sessions, ids, actor = independent_capability_mysql
    stores = StoreAdminService(sessions)
    with sessions() as reader, reader.begin():
        connection_a = reader.scalar(text('SELECT CONNECTION_ID()'))
        # 事务 A 此处建立 Read View，并保留 ORM 对象缓存；一直不结束该事务。
        assert reader.scalar(select(DatasetState.data_version)) == 7
        cached = [*reader.scalars(select(StoreProfile)), *reader.scalars(select(Department)),
                  *reader.scalars(select(Employee)), *reader.scalars(select(EmployeeDepartment))]
        with sessions.begin() as writer:
            assert writer.scalar(text('SELECT CONNECTION_ID()')) != connection_a
            state = writer.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
            writer.get(StoreProfile, ids['shop']).notes = 'committed-notes'
            writer.get(StoreProfile, ids['other']).is_store = True
            writer.get(Department, ids['leaf']).parent_id = ids['other']
            writer.get(Employee, ids['u']).status = 'inactive'
            writer.get(EmployeeDepartment, (ids['w'], ids['leaf'])).active = False
            writer.add(Employee(id=ids['new'], feishu_user_id=ids['new'], name='new', primary_department_id=ids['leaf'], status='active', sync_quality='complete'))
            writer.flush()
            writer.add(EmployeeDepartment(employee_id=ids['new'], department_id=ids['leaf'], active=True, is_primary=True))
            state.data_version = 8
        assert reader.scalar(select(DatasetState.data_version)) == 7
        assert cached  # 缓存对象在借用事务调用期间保持存活。
        result = stores.apply_in_session(reader, [StorePatch(ids['shop'], True)], 8, actor, datetime.now())
        assert (result.data_version, result.changed_count) == (9, 1)
    with sessions() as db:
        assert db.get(StoreProfile, ids['shop']).notes == 'committed-notes'
        log = db.get(ChangeLog, result.audit_ids[0])
        assert log.before_data['notes'] == log.after_data['notes'] == 'committed-notes'
        assert db.get(EmployeeStore, (ids['u'], ids['shop'])) is None
        assert db.get(EmployeeStore, (ids['w'], ids['shop'])) is None
        assert list(db.scalars(select(EmployeeStore).where(EmployeeStore.employee_id.in_([ids['u'], ids['w']])))) == []
        projection = db.get(EmployeeStore, (ids['new'], ids['other']))
        assert projection.is_primary and projection.path == [ids['leaf'], ids['other']]
        assert db.get(Employee, ids['u']).primary_store_status == 'inactive'
        assert db.get(Employee, ids['w']).primary_store_status == 'inconsistent'
        assert db.get(Employee, ids['new']).primary_store_status == 'resolved'
        assert db.get(DatasetState, 1).data_version == 9


@pytest.mark.parametrize('dependency,error_code', [('department', 'DEPARTMENT_INACTIVE'), ('reservation', 'STORE_CODE_RESERVED')])
def test_borrowed_rr_validates_current_department_and_code_reservation(independent_capability_mysql, dependency, error_code):
    sessions, ids, actor = independent_capability_mysql
    code = actor + '_code'
    with sessions() as reader, reader.begin():
        connection_a = reader.scalar(text('SELECT CONNECTION_ID()'))
        assert reader.scalar(select(DatasetState.data_version)) == 7
        cached_department = reader.get(Department, ids['shop'])
        assert reader.get(StoreCodeReservation, code) is None
        with sessions.begin() as writer:
            assert writer.scalar(text('SELECT CONNECTION_ID()')) != connection_a
            state = writer.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
            if dependency == 'department': writer.get(Department, ids['shop']).status = 'inactive'
            else: writer.add(StoreCodeReservation(store_code=code, department_id=ids['other'], reserved_at=datetime.now()))
            state.data_version = 8
        assert cached_department.status == 'active'
        assert reader.scalar(select(DatasetState.data_version)) == 7
        with pytest.raises(InvalidStoreChanges) as caught:
            StoreAdminService(sessions).apply_in_session(reader, [StorePatch(ids['shop'], True, code)], 8, actor, datetime.now())
        assert [error.code for error in caught.value.errors] == [error_code]
    with sessions() as db:
        assert db.get(StoreProfile, ids['shop']).is_store is False
        assert db.get(DatasetState, 1).data_version == 8
        assert list(db.scalars(select(ChangeLog).where(ChangeLog.actor == actor))) == []


def capability(sessions, receipts=None):
    return OrganizationCapabilities(
        sessions, SqlReadService(sessions, 'mysql-acceptance-cursor-secret'),
        StoreAdminService(sessions), SqlSyncJobRepository(sessions),
        receipts or ReceiptRepository(), ObservationService(), environment='test',
    )


def context(actor):
    return AgentContext('ci_agent', actor, 'test', run_id='test-' + actor)


@pytest.mark.parametrize('same_key', [False, True], ids=['one-version-wins', 'same-key-one-operation'])
def test_concurrent_apply_uses_independent_connections_and_atomic_receipts(independent_capability_mysql, same_key):
    sessions, ids, actor = independent_capability_mysql
    held, attempted, release = Event(), Event(), Event()
    connection_ids = set()

    class HoldingReceipts(ReceiptRepository):
        def create(self, db, *args):
            connection_ids.add(db.scalar(text('SELECT CONNECTION_ID()')))
            row = super().create(db, *args)
            held.set()  # 回执已插入，DatasetState 行锁仍由事务 A 持有。
            assert release.wait(10), '事务 A 等待释放超时'
            return row

    class ContendingReceipts(ReceiptRepository):
        def _lock_state(self, db):
            connection_ids.add(db.scalar(text('SELECT CONNECTION_ID()')))
            attempted.set()  # 事务 B 已建立独立连接，即将竞争同一行锁。
            return super()._lock_state(db)

    def apply(receipts, key):
        try:
            return capability(sessions, receipts).apply_store_changes(
                context(actor), [StorePatch(ids['shop'], True)], 7, key, expected_epoch=actor,
            )
        except CapabilityError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        winner = executor.submit(apply, HoldingReceipts(), 'apply-first')
        try:
            assert held.wait(10), '事务 A 未持有行锁'
            contender = executor.submit(apply, ContendingReceipts(), 'apply-first' if same_key else 'apply-second')
            assert attempted.wait(10), '事务 B 未开始竞争'
            assert len(connection_ids) == 2, '必须使用两个真实 MySQL 连接'
            assert not contender.done(), '事务 A 释放前事务 B 不应完成'
        finally:
            release.set()
        first, second = winner.result(timeout=10), contender.result(timeout=10)
    assert not isinstance(first, CapabilityError)
    assert first.observation.data_version == 8
    if same_key:
        assert second.to_dict() == first.to_dict()
        assert second.operation_id == first.operation_id
    else:
        assert isinstance(second, DatasetChangedError)
    with sessions() as db:
        assert db.get(DatasetState, 1).data_version == 8
        assert db.get(StoreProfile, ids['shop']).is_store is True
        assert db.get(StoreProfile, ids['shop']).notes == 'old-notes'
        assert len(list(db.scalars(select(EmployeeStore)))) == 2
        receipts = list(db.scalars(select(OperationReceipt).where(OperationReceipt.actor_id == actor)))
        audits = list(db.scalars(select(ChangeLog).where(ChangeLog.actor == actor)))
        assert len(receipts) == len(audits) == 1
        assert receipts[0].result_summary['audit_ids'] == [audits[0].id]
        assert (receipts[0].committed_epoch, receipts[0].committed_version) == (actor, 8)


@pytest.mark.parametrize('failure', ['audit', 'receipt'])
def test_mysql_audit_or_receipt_failure_rolls_back_business_transaction(independent_capability_mysql, failure):
    sessions, ids, actor = independent_capability_mysql
    model, hook = (ChangeLog, 'before_insert') if failure == 'audit' else (OperationReceipt, 'before_update')

    def injected(*_):
        raise RuntimeError('INJECTED_MYSQL_WRITE_FAILURE')

    event.listen(model, hook, injected)
    try:
        with pytest.raises(CapabilityUnavailable):
            capability(sessions).apply_store_changes(context(actor), [StorePatch(ids['shop'], True)], 7, 'rollback', expected_epoch=actor)
    finally:
        event.remove(model, hook, injected)
    with sessions() as db:
        assert db.get(DatasetState, 1).data_version == 7
        profile = db.get(StoreProfile, ids['shop'])
        assert profile.is_store is False and profile.notes == 'old-notes'
        assert list(db.scalars(select(EmployeeStore))) == []
        assert list(db.scalars(select(ChangeLog).where(ChangeLog.actor == actor))) == []
        assert list(db.scalars(select(OperationReceipt).where(OperationReceipt.actor_id == actor))) == []


@pytest.mark.parametrize('outcome', ['succeeded', 'failed'])
def test_mysql_job_receipt_follows_real_sync_job_finalization(independent_capability_mysql, outcome):
    sessions, ids, actor = independent_capability_mysql
    service = capability(sessions)
    accepted = service.request_sync(context(actor), 'full', 'sync')
    job_id = accepted.data['job_id']
    assert accepted.observation.execution == 'accepted'
    assert service.request_sync(context(actor), 'full', 'sync').operation_id == accepted.operation_id
    jobs = SqlSyncJobRepository(sessions)
    running = jobs.claim_next(datetime.now(), datetime.now() + timedelta(minutes=5))
    assert running.id == job_id
    assert service.get_operation(context(actor), operation_id=accepted.operation_id).observation.execution == 'running'
    if outcome == 'succeeded':
        Publisher(sessions).publish(Candidate(departments={ids['shop']: {
            'id': ids['shop'], 'feishu_department_id': ids['shop'], 'parent_id': None,
            'name': '真实发布后的门店', 'status': 'active', 'sync_quality': 'complete', 'is_virtual_root': False,
        }}), job_id, running.lease_generation)
    else:
        jobs.mark_failed(job_id, running.lease_generation, 'REMOTE_ERROR', 'injected failure', datetime.now())
    result = service.get_operation(context(actor), operation_id=accepted.operation_id)
    assert result.observation.execution == ('submitted' if outcome == 'succeeded' else 'failed')
    with sessions() as db:
        job, receipt = db.get(SyncJob, job_id), db.get(OperationReceipt, accepted.operation_id)
        assert job.trigger_source == 'ci_agent' and job.requested_by == actor
        assert receipt.actor_id == actor
        assert job.status == outcome
        assert receipt.status == ('submitted' if outcome == 'succeeded' else 'failed')
        assert receipt.error_code == (None if outcome == 'succeeded' else 'REMOTE_ERROR')
        assert (receipt.committed_epoch, receipt.committed_version) == (actor, 8 if outcome == 'succeeded' else 7)
        audit_ids = list(db.scalars(select(ChangeLog.id).where(ChangeLog.job_id == job_id).order_by(ChangeLog.id)))
        assert receipt.result_summary['audit_ids'] == audit_ids
        assert len(audit_ids) == (1 if outcome == 'succeeded' else 0)


@pytest.mark.parametrize('receipt_type', ['store', 'job'])
def test_mysql_old_epoch_receipt_cannot_claim_current_dataset(independent_capability_mysql, receipt_type):
    sessions, ids, actor = independent_capability_mysql
    service = capability(sessions)
    if receipt_type == 'store':
        result = service.apply_store_changes(context(actor), [StorePatch(ids['shop'], True)], 7, 'old', expected_epoch=actor)
    else:
        result = service.request_sync(context(actor), 'full', 'old')
        running = SqlSyncJobRepository(sessions).claim_next(datetime.now(), datetime.now() + timedelta(minutes=5))
    with sessions.begin() as db:
        state = db.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
        state.dataset_epoch, state.data_version = actor + '_restored', 100
    if receipt_type == 'job':
        Publisher(sessions).publish(Candidate(), running.id, running.lease_generation)
    historical = service.get_operation(context(actor), operation_id=result.operation_id)
    assert historical.observation.execution == 'unconfirmed'
    assert historical.observation.fact_quality == 'inconsistent'
    assert historical.observation.dataset_epoch == actor
    assert historical.observation.data_version == (8 if receipt_type == 'store' else 7)
    assert historical.observation.evidence['current_dataset_epoch'] == actor + '_restored'
    assert historical.observation.evidence['current_data_version'] == 100
    if receipt_type == 'job':
        assert historical.data['status'] == 'failed' and historical.data['error_code'] == 'DATASET_CHANGED'
    with pytest.raises(DatasetChangedError):
        service.apply_store_changes(context(actor), [StorePatch(ids['shop'], False)], 100, 'stale', expected_epoch=actor)
    with sessions() as db:
        assert db.get(DatasetState, 1).data_version == 100
        assert db.scalar(select(func.count()).select_from(OperationReceipt).where(OperationReceipt.actor_id == actor)) == 1


def test_mysql_actual_session_pool_reuse_reconnect_and_receipt_schema(independent_capability_mysql):
    sessions, _, _ = independent_capability_mysql
    engine = sessions.kw['bind']

    def check_session(db):
        assert tuple(db.execute(text('SELECT @@character_set_client,@@character_set_connection,@@character_set_results,@@collation_connection')).one()) == ('utf8mb4', 'utf8mb4', 'utf8mb4', 'utf8mb4_0900_as_cs')
        return db.scalar(text('SELECT CONNECTION_ID()'))

    with engine.connect() as first:
        first_id = check_session(first)
        with engine.connect() as independent:
            assert check_session(independent) != first_id
    # QueuePool 先归还的连接会先被复用；两个空闲连接均需保留会话设置。
    with engine.connect() as reused:
        reused_id = check_session(reused)
    with engine.connect() as spare, engine.connect() as reconnected:
        old_ids = {check_session(spare), check_session(reconnected)}
        assert old_ids == {first_id, reused_id}
        reconnected.invalidate()
        reconnected.rollback()
        assert check_session(reconnected) not in old_ids
        table = reconnected.execute(text("SELECT ENGINE,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='operation_receipt'")).one()
        assert tuple(table) == ('InnoDB', 'utf8mb4_0900_as_cs')
        columns = reconnected.execute(text("SELECT COLUMN_NAME,CHARACTER_SET_NAME,COLLATION_NAME,COLUMN_COMMENT FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='operation_receipt'")).all()
        assert len(columns) == len(OperationReceipt.__table__.columns)
        for name, charset, collation, comment in columns:
            expected = OperationReceipt.__table__.c[name]
            assert comment == expected.comment
            if charset:
                assert charset == 'utf8mb4'
                assert collation == (getattr(expected.type, 'collation', None) or 'utf8mb4_0900_as_cs')
        ddl = reconnected.execute(text('SHOW CREATE TABLE operation_receipt')).one()[1]
        assert 'ENGINE=InnoDB' in ddl and 'COLLATE=utf8mb4_0900_as_cs' in ddl
        assert 'UNIQUE KEY `uq_operation_receipt_idempotency` (`actor_id`,`environment`,`idempotency_key`)' in ddl


def test_mysql_terminal_detail_snapshot_uses_current_read_and_survives_retry(independent_capability_mysql):
    sessions, ids, actor = independent_capability_mysql
    service = capability(sessions)
    accepted = service.request_sync(context(actor), 'full', 'detail-snapshot')
    job_id = accepted.data['job_id']
    jobs = SqlSyncJobRepository(sessions)
    running = jobs.claim_next(datetime.now(), datetime.now() + timedelta(minutes=5))
    with sessions() as reader, reader.begin():
        reader_id = reader.scalar(text('SELECT CONNECTION_ID()'))
        # 先建立看不到失败明细的旧 Read View，再由独立事务记录失败。
        assert list(reader.scalars(select(SyncJobDetail.id).where(SyncJobDetail.job_id == job_id))) == []
        with sessions.begin() as writer:
            assert writer.scalar(text('SELECT CONNECTION_ID()')) != reader_id
            writer.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
            job = writer.scalar(select(SyncJob).where(SyncJob.id == job_id).with_for_update())
            Publisher._record_detail(writer, job_id, 'department', ids['shop'], None, 'failed', datetime.now(), error_code='REMOTE_ERROR')
            job.failure_count = 1
        reader.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
        job = reader.scalar(select(SyncJob).where(SyncJob.id == job_id).with_for_update().execution_options(populate_existing=True))
        job.status, job.error_code, job.lease_expires_at = 'failed', 'REMOTE_ERROR', None
        ReceiptRepository().finalize_job_in_session(reader, job, datetime.now())
    original = service.get_operation(context(actor), operation_id=accepted.operation_id)
    assert original.data['summary']['failed_detail_count'] == 1
    assert original.observation.evidence['failed_detail_count'] == 1
    retried = service.retry_sync_job(context(actor), job_id, 'detail-snapshot-retry')
    running = jobs.claim_next(datetime.now(), datetime.now() + timedelta(minutes=5))
    with sessions.begin() as db:
        db.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
        job = db.scalar(select(SyncJob).where(SyncJob.id == job_id).with_for_update())
        Publisher._record_detail(db, job_id, 'department', ids['shop'], None, 'succeeded', datetime.now())
        job.success_count, job.failure_count = 1, 0
    jobs.mark_succeeded(job_id, running.lease_generation, datetime.now())
    assert service.get_operation(context(actor), operation_id=accepted.operation_id).to_dict() == original.to_dict()
    latest = service.get_operation(context(actor), operation_id=retried.operation_id)
    assert latest.data['summary']['failed_detail_count'] == 0
    assert latest.observation.execution == 'submitted'
