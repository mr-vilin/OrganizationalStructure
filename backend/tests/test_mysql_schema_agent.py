from pathlib import Path
import importlib.util

from alembic.config import Config
from alembic import command

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "versions" / "0007_operation_receipt.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("migration_0007_operation_receipt", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_operation_receipt_migration_metadata_and_source_contract():
    module = load_migration()
    assert module.revision == "0007_operation_receipt"
    assert module.down_revision == "0006_column_comments"
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
    command.upgrade(config, "0006_column_comments:0007_operation_receipt", sql=True)
    sql = buf.getvalue()
    assert "CREATE TABLE operation_receipt" in sql
    assert "ENGINE=InnoDB" in sql
    assert "utf8mb4" in sql
    assert "操作回执" in sql
    assert "uq_operation_receipt_idempotency" in sql
    assert "ix_operation_receipt_job_id" in sql
    assert "ALTER TABLE sync_job" not in sql

