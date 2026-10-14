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

