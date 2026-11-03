from pathlib import Path
import importlib.util

from alembic.config import Config
from alembic import command
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.persistence.models import OperationReceipt

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "versions" / "0009_operation_receipt.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("migration_0009_operation_receipt", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_operation_receipt_migration_metadata_and_source_contract():
    module = load_migration()
    assert module.revision == "0009_operation_receipt"
    assert module.down_revision == "0008_session_digest"
    source = MIGRATION.read_text(encoding="utf-8")
    for text in ("操作回执", "uq_operation_receipt_idempotency", "ix_operation_receipt_job_id", "ix_operation_receipt_case_id", "ix_operation_receipt_status", "ix_operation_receipt_created_at"):
        assert text in source
    assert "drop_table(\"operation_receipt\")" in source
    assert "sync_job" not in source.replace("sync_job_id", "")


def test_operation_receipt_offline_sql_contains_only_new_table():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "mysql+pymysql://unused:unused@localhost/unused")
    # Generate only this revision so no existing tables are mutated by this test.
    from io import StringIO
    buf = StringIO()
    config.output_buffer = buf
    command.upgrade(config, "0008_session_digest:0009_operation_receipt", sql=True)
    sql = buf.getvalue()
    assert "CREATE TABLE operation_receipt" in sql
    assert "ENGINE=InnoDB" in sql
    assert "utf8mb4" in sql
    assert "COLLATE utf8mb4_general_ci" in sql
    assert "操作回执" in sql
    assert "uq_operation_receipt_idempotency" in sql
    assert "ix_operation_receipt_job_id" in sql
    assert "ALTER TABLE sync_job" not in sql


def test_operation_receipt_orm_and_migration_preserve_comments_and_binary_ids():
    table = OperationReceipt.__table__
    ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
    assert "COLLATE utf8mb4_general_ci" in ddl
    assert "ENGINE=InnoDB" in ddl and "CHARSET=utf8mb4" in ddl
    for column in table.columns:
        assert column.comment and any('\u4e00' <= char <= '\u9fff' for char in column.comment)
        assert column.comment in ddl
    assert table.c.operation_id.type.collation == 'utf8mb4_bin'
    assert table.c.idempotency_key.type.collation == 'utf8mb4_bin'
    source = MIGRATION.read_text(encoding='utf-8')
    for column in table.columns:
        assert column.comment in source


def test_mysql_engine_explicitly_sets_session_charset_and_collation(monkeypatch):
    from app.persistence import database
    calls = []
    listeners = []
    monkeypatch.setattr(database, 'create_engine', lambda *args, **kwargs: calls.append((args, kwargs)))
    def register(target, identifier):
        def decorator(listener):
            listeners.append((target, identifier, listener))
            return listener
        return decorator
    monkeypatch.setattr(database.event, 'listens_for', register)
    database.create_mysql_engine('mysql+pymysql://unused:unused@localhost/unused_test?charset=latin1')
    options = calls[0][1]
    assert options['connect_args'] == {'charset': 'utf8mb4'}
    assert options['isolation_level'] == 'REPEATABLE READ'
    assert options['hide_parameters'] is True
    from unittest.mock import Mock
    connection = Mock()
    assert listeners[0][1] == 'connect'
    listeners[0][2](connection, None)
    from unittest.mock import call
    assert connection.cursor.return_value.execute.call_args_list == [
        call("SET NAMES utf8mb4 COLLATE utf8mb4_general_ci"), call("SET time_zone = '+00:00'")]
    connection.cursor.return_value.close.assert_called_once()
