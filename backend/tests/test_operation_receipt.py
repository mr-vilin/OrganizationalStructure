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
