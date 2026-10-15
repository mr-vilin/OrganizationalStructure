from pathlib import Path
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable
from app.persistence.models import OperationReceipt


def test_operation_receipt_ddl_is_innodb_utf8mb4_and_has_chinese_comments():
    ddl = str(CreateTable(OperationReceipt.__table__).compile(dialect=mysql.dialect()))
    assert "ENGINE=InnoDB" in ddl
    assert "CHARSET=utf8mb4" in ddl
    assert "COMMENT='Agent 操作回执记录'" in ddl
    assert "COMMENT '操作回执" in ddl or "COMMENT='操作回执" in ddl
    for column in OperationReceipt.__table__.columns:
        assert column.comment, column.name
        assert any("\u4e00" <= char <= "\u9fff" for char in column.comment), column.name


def test_operation_receipt_primary_unique_constraint_and_indexes():
    table = OperationReceipt.__table__
    assert [column.name for column in table.primary_key.columns] == ["operation_id"]
    constraints = {constraint.name: tuple(column.name for column in constraint.columns) for constraint in table.constraints if constraint.name}
    assert constraints["uq_operation_receipt_idempotency"] == ("actor_id", "environment", "idempotency_key")
    indexes = {index.name: tuple(column.name for column in index.columns) for index in table.indexes}
    for column in ("job_id", "case_id", "status", "created_at"):
        assert any(column in columns for columns in indexes.values()), column


def test_operation_receipt_has_expected_columns_and_nullability():
    table = OperationReceipt.__table__
    expected = {
        "operation_id", "idempotency_key", "capability", "actor_type", "actor_id", "environment",
        "run_id", "case_id", "request_hash", "status", "job_id", "before_epoch", "before_version",
        "committed_epoch", "committed_version", "result_summary", "error_code", "created_at", "updated_at",
    }
    assert {column.name for column in table.columns} == expected
    for name in ("operation_id", "idempotency_key", "capability", "actor_type", "actor_id", "environment", "request_hash", "status", "before_epoch", "before_version", "created_at", "updated_at"):
        assert table.c[name].nullable is False, name
    for name in ("run_id", "case_id", "job_id", "committed_epoch", "committed_version", "result_summary", "error_code"):
        assert table.c[name].nullable is True, name


from datetime import datetime
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.capabilities.contracts import AgentContext
from app.capabilities.errors import OperationConflict
from app.capabilities.receipts import ReceiptRepository
from app.persistence.models import Base, DatasetState

@pytest.fixture
def receipt_sessions():
    engine = create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def configure(connection, _):
        connection.create_collation('utf8mb4_bin', lambda a, b: (a > b) - (a < b))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(DatasetState(id=1, dataset_epoch='e', data_version=1, initialization_status='complete'))
    yield factory
    engine.dispose()

def receipt_ctx():
    return AgentContext('human_agent', 'actor', 'test', run_id='run', case_id='case')

def test_receipt_idempotency_and_updates(receipt_sessions):
    repo = ReceiptRepository(); now = datetime(2026, 1, 1)
    with receipt_sessions.begin() as db:
        first = repo.create(db, receipt_ctx(), 'request_sync', 'key', 'hash-a', now)
        assert repo.create(db, receipt_ctx(), 'request_sync', 'key', 'hash-a', now).operation_id == first.operation_id
        with pytest.raises(OperationConflict): repo.create(db, receipt_ctx(), 'request_sync', 'key', 'hash-b', now)
        repo.mark_accepted(db, first.operation_id, 'job', 'e', 1, {'job_id': 'job'}, now)
        repo.mark_submitted(db, first.operation_id, 'e2', 2, {'changed_count': 1}, [3, 4], now)
    with receipt_sessions() as db:
        row = repo.get_by_idempotency(db, 'actor', 'test', 'key')
        assert row.status == 'submitted' and row.committed_epoch == 'e2' and row.committed_version == 2
        assert row.result_summary['audit_ids'] == [3, 4]

def test_receipt_create_rolls_back(receipt_sessions):
    repo = ReceiptRepository()
    with pytest.raises(RuntimeError):
        with receipt_sessions.begin() as db:
            repo.create(db, receipt_ctx(), 'x', 'rollback', 'h', datetime.now())
            raise RuntimeError('rollback')
    with receipt_sessions() as db:
        assert repo.get_by_idempotency(db, 'actor', 'test', 'rollback') is None

def test_receipt_failed_update_and_secret_redaction(receipt_sessions):
    repo = ReceiptRepository(); now = datetime(2026, 1, 1)
    with receipt_sessions.begin() as db:
        row = repo.create(db, receipt_ctx(), 'request_sync', 'failed', 'hash', now)
        repo.mark_failed(db, row.operation_id, 'REMOTE_ERROR', {'token': 'secret', 'message': 'failed'}, now)
    with receipt_sessions() as db:
        row = repo.get_by_idempotency(db, 'actor', 'test', 'failed')
        assert row.status == 'failed' and row.error_code == 'REMOTE_ERROR'
        assert row.result_summary['token'] == '[REDACTED]'

@pytest.mark.parametrize('late', ['accepted', 'submitted', 'failed'])
def test_completed_receipt_rejects_conflicting_result(receipt_sessions, late):
    repo = ReceiptRepository(); now = datetime(2026, 1, 1)
    with receipt_sessions.begin() as db:
        row = repo.create(db, receipt_ctx(), 'apply', 'terminal', 'hash', now)
        repo.mark_accepted(db, row.operation_id, 'job', 'e', 1, {}, now)
        repo.mark_submitted(db, row.operation_id, 'e', 2, {'changed_count': 2}, [1, 2], now)
        assert repo.mark_submitted(db, row.operation_id, 'e', 2, {'changed_count': 2}, [1, 2], now) is row
        with pytest.raises(OperationConflict):
            if late == 'accepted': repo.mark_accepted(db, row.operation_id, 'another', 'e', 0, {}, now)
            elif late == 'submitted': repo.mark_submitted(db, row.operation_id, 'e', 3, {}, [3], now)
            else: repo.mark_failed(db, row.operation_id, 'LATE_FAILURE', {}, now)
        assert (row.status, row.job_id, row.committed_version, row.result_summary['audit_ids']) == ('submitted', 'job', 2, [1, 2])


def test_failed_is_terminal_and_accepted_cannot_rebind(receipt_sessions):
    repo = ReceiptRepository(); now = datetime(2026, 1, 1)
    with receipt_sessions.begin() as db:
        row = repo.create(db, receipt_ctx(), 'sync', 'transitions', 'hash', now)
        repo.mark_accepted(db, row.operation_id, 'job', 'e', 1, {}, now)
        assert repo.mark_accepted(db, row.operation_id, 'job', 'e', 1, {}, now) is row
        with pytest.raises(OperationConflict): repo.mark_accepted(db, row.operation_id, 'other', 'e', 1, {}, now)
        repo.mark_failed(db, row.operation_id, 'REMOTE_ERROR', {}, now)
        assert repo.mark_failed(db, row.operation_id, 'REMOTE_ERROR', {}, now) is row
        with pytest.raises(OperationConflict): repo.mark_failed(db, row.operation_id, 'OTHER_ERROR', {}, now)
        with pytest.raises(OperationConflict): repo.mark_submitted(db, row.operation_id, 'e', 2, {}, [], now)
        with pytest.raises(OperationConflict): repo.mark_accepted(db, row.operation_id, 'job', 'e', 1, {}, now)
        assert row.job_id == 'job' and row.error_code == 'REMOTE_ERROR'


def test_complete_audit_ids_and_untrusted_text(receipt_sessions):
    repo = ReceiptRepository(); now = datetime(2026, 1, 1)
    with receipt_sessions.begin() as db:
        row = repo.create(db, receipt_ctx(), 'apply', 'audit', 'hash', now)
        repo.mark_submitted(db, row.operation_id, 'e', 2, {
            'changed_count': 101, 'message': 'Bearer SYNTHETIC_SECRET',
            'detail': ['Authorization: SYNTHETIC_SECRET', {'url': 'https://x/?code=SYNTHETIC_SECRET'}],
            'custom': 'OAuth SYNTHETIC_SECRET', 'token': 'SYNTHETIC_SECRET',
        }, list(range(101)), now)
    with receipt_sessions() as db:
        import json
        row = repo.get_by_idempotency(db, 'actor', 'test', 'audit')
        assert row.result_summary['audit_ids'] == list(range(101))
        assert row.result_summary['changed_count'] == 101
        assert 'SYNTHETIC_SECRET' not in json.dumps(row.result_summary)


def test_create_locks_dataset_before_current_idempotency_read(receipt_sessions):
    from sqlalchemy import event
    statements = []
    repo = ReceiptRepository(); now = datetime(2026, 1, 1)
    with receipt_sessions.begin() as db:
        @event.listens_for(db, 'do_orm_execute')
        def record(execute_state):
            statements.append(execute_state.statement)
        first = repo.create(db, receipt_ctx(), 'sync', 'lock-order', 'hash', now)
        assert repo.create(db, receipt_ctx(), 'sync', 'lock-order', 'hash', now) is first
    assert [str(stmt.get_final_froms()[0]) for stmt in statements[:2]] == ['dataset_state', 'operation_receipt']
    assert all(stmt._for_update_arg is not None for stmt in statements)
    assert all(stmt.get_execution_options().get('populate_existing') for stmt in statements)

def test_submitted_cannot_regress_same_epoch_version(receipt_sessions):
    repo = ReceiptRepository(); now = datetime(2026, 1, 1)
    with receipt_sessions.begin() as db:
        row = repo.create(db, receipt_ctx(), 'sync', 'version', 'hash', now)
        repo.mark_accepted(db, row.operation_id, 'job', 'e', 4, {}, now)
        with pytest.raises(OperationConflict): repo.mark_submitted(db, row.operation_id, 'e', 3, {}, [], now)
        assert row.status == 'accepted' and row.committed_version == 4


def test_stale_session_cannot_overwrite_terminal_receipt(receipt_sessions):
    repo = ReceiptRepository(); now = datetime(2026, 1, 1)
    with receipt_sessions.begin() as db:
        operation_id = repo.create(db, receipt_ctx(), 'sync', 'stale', 'hash', now).operation_id
    with receipt_sessions() as stale:
        cached = repo.get_by_idempotency(stale, 'actor', 'test', 'stale')
        stale.commit()
        with receipt_sessions.begin() as other:
            repo.mark_submitted(other, operation_id, 'e', 2, {}, [1], now)
        assert cached.status == 'recorded'
        with pytest.raises(OperationConflict): repo.mark_failed(stale, operation_id, 'LATE_ERROR', {}, now)
        assert cached.status == 'submitted'


@pytest.mark.parametrize('action', ['accepted', 'submitted', 'failed'])
def test_receipt_update_participates_in_caller_rollback(receipt_sessions, action):
    repo = ReceiptRepository(); now = datetime(2026, 1, 1)
    with receipt_sessions.begin() as db:
        operation_id = repo.create(db, receipt_ctx(), 'sync', 'update-rollback', 'hash', now).operation_id
    with pytest.raises(RuntimeError):
        with receipt_sessions.begin() as db:
            if action == 'accepted': repo.mark_accepted(db, operation_id, 'job', 'e', 1, {}, now)
            elif action == 'submitted': repo.mark_submitted(db, operation_id, 'e', 2, {}, [1], now)
            else: repo.mark_failed(db, operation_id, 'ERROR', {}, now)
            raise RuntimeError('caller rollback')
    with receipt_sessions() as db:
        row = repo.get_by_idempotency(db, 'actor', 'test', 'update-rollback')
        assert row.status == 'recorded' and row.result_summary is None


@pytest.mark.parametrize('bad_id', [True, -1, {}, 'Bearer SYNTHETIC_SECRET'])
def test_invalid_audit_id_rejected_without_overwriting_result(receipt_sessions, bad_id):
    repo = ReceiptRepository(); now = datetime(2026, 1, 1)
    with receipt_sessions.begin() as db:
        row = repo.create(db, receipt_ctx(), 'apply', 'bad-audit', 'hash', now)
        with pytest.raises(OperationConflict): repo.mark_submitted(db, row.operation_id, 'e', 2, {}, [bad_id], now)
        assert row.status == 'recorded'


@pytest.mark.parametrize("epoch_changed", [False, True])
def test_review_i3_failure_freezes_all_audit_ids_in_original_transaction(receipt_sessions, epoch_changed):
    from app.persistence.models import ChangeLog, SyncJob
    repo = ReceiptRepository()
    now = datetime(2026, 1, 1)
    with receipt_sessions.begin() as db:
        row = repo.create(db, receipt_ctx(), "request_sync", "failure-audit", "hash", now)
        operation_id = row.operation_id
        repo.mark_accepted(db, row.operation_id, "job", "e", 1, {}, now)
        job = SyncJob(id="job", type="full", requested_by="actor", status="failed", error_code="SYNC_FAILED", created_at=now, updated_at=now)
        db.add(job)
        for identifier in range(1, 126):
            db.add(ChangeLog(id=identifier, object_type="sync_job", object_id="job", job_id="job", source="sync", actor="actor", after_data={"status":"failed"}, committed_at=now))
        if epoch_changed: db.get(DatasetState, 1).dataset_epoch = "restored"
        repo.finalize_job_in_session(db, job, now)
    with receipt_sessions() as db:
        row = db.get(OperationReceipt, operation_id)
        assert row.result_summary["audit_ids"] == list(range(1, 126))
        assert row.status == "failed" and row.committed_epoch == "e" and row.committed_version == 1
        assert row.error_code == ("DATASET_CHANGED" if epoch_changed else "SYNC_FAILED")
    with receipt_sessions.begin() as db:
        db.add(ChangeLog(id=126, object_type="sync_job", object_id="job", job_id="job", source="admin", actor="actor", after_data={"status":"queued"}, committed_at=now))
        repo.finalize_job_in_session(db, db.get(SyncJob, "job"), now)
    with receipt_sessions() as db:
        assert db.get(OperationReceipt, operation_id).result_summary["audit_ids"] == list(range(1, 126))
