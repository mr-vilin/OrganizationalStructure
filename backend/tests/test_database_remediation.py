from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import text
from fastapi.testclient import TestClient
import pytest

from app.persistence.models import AdminAllowlist, Base
from app.persistence.repositories import SqlIdentityRepository
from db_fixtures import create_sqlite_sessions


def _sessions():
    return create_sqlite_sessions(seed_worker_lease=True)


def test_mysql_escaped_json_default_matches_empty_object_only():
    from app.persistence.schema_check import _default
    from migrations.schema_20261022 import normalize_default

    for normalize in (_default, normalize_default):
        assert normalize(r"_utf8mb4\'{}\'") == normalize("('{}')")
        assert normalize(r"_utf8mb4\'[]\'") != normalize("('{}')")
        assert normalize(None) is None


def test_session_cookie_is_sha256_digest_lookup_and_digest_is_not_a_valid_cookie():
    engine, sessions = _sessions()
    try:
        now = datetime(2026, 10, 22, tzinfo=timezone.utc).replace(tzinfo=None)
        with sessions.begin() as db:
            db.add(AdminAllowlist(open_id="ou_admin", created_at=now))

        issued = SqlIdentityRepository(sessions, "s" * 32).create_session(
            "ou_admin", "csrf", now + timedelta(hours=1), now
        )

        assert issued.token != issued.record.token_digest
        assert SqlIdentityRepository(sessions, "s" * 32).authenticate_session(issued.token, now)
        assert SqlIdentityRepository(sessions, "s" * 32).authenticate_session(issued.record.token_digest, now) is None
        assert SqlIdentityRepository(sessions, "s" * 32).authenticate_session(issued.record.id, now) is None
        assert SqlIdentityRepository(sessions, "s" * 32).authenticate_session(issued.token, now + timedelta(hours=2)) is None
        assert SqlIdentityRepository(sessions, "s" * 32).revoke_session(issued.record.id, now)
        assert SqlIdentityRepository(sessions, "s" * 32).authenticate_session(issued.token, now) is None
    finally:
        engine.dispose()


def test_database_ready_is_read_only_and_requires_the_supported_schema_head():
    from app.persistence.database import database_ready

    engine, _ = _sessions()
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0009_operation_receipt')"))

        report = database_ready(engine, expected_head="0009_operation_receipt")

        assert report == {"database": "ready", "schema": "ready"}
    finally:
        engine.dispose()


def test_schema_snapshot_exposes_columns_comments_defaults_collations_and_constraints():
    from app.persistence.database import schema_snapshot

    engine, _ = _sessions()
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0009_operation_receipt')"))

        snapshot = schema_snapshot(engine)

        assert snapshot["versions"] == ["0009_operation_receipt"]
        assert "token_digest" in {column["name"] for column in snapshot["tables"]["admin_session"]["columns"]}
        assert {"columns", "indexes", "foreign_keys", "comment"} <= set(snapshot["tables"]["admin_session"])
    finally:
        engine.dispose()


def test_readiness_does_not_initialize_or_mutate_the_admin_allowlist():
    import app.main as main
    from app.dependencies import get_runtime

    calls = []
    runtime = SimpleNamespace(engine=object(), identities=SimpleNamespace(initialize_allowlist_once=lambda *_: calls.append(True)))
    app = main.app
    app.dependency_overrides[get_runtime] = lambda: runtime
    previous = main.database_ready
    main.database_ready = lambda _: {"database": "ready", "schema": "ready"}
    try:
        response = TestClient(app).get("/health/ready")
    finally:
        main.database_ready = previous
        app.dependency_overrides.pop(get_runtime, None)

    assert response.status_code == 200
    assert calls == []


@pytest.mark.parametrize("damage", [
    "DROP TABLE alembic_version",
    "DELETE FROM alembic_version",
    "UPDATE alembic_version SET version_num='0006_column_comments'",
    "UPDATE alembic_version SET version_num='unknown_head'",
    "INSERT INTO alembic_version VALUES ('other_head')",
    "DROP TABLE employee_store",
    "ALTER TABLE admin_session DROP COLUMN csrf_hash",
    "DELETE FROM dataset_state",
    "DELETE FROM worker_lease",
    "DELETE FROM system_setting",
])
def test_readiness_rejects_incomplete_schema_without_writing(damage):
    from app.main import app
    from app.dependencies import get_runtime

    engine, _ = _sessions()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0009_operation_receipt')"))
        connection.execute(text(damage))
        connection.execute(text("PRAGMA query_only=ON"))
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace(engine=engine)
    try:
        response = TestClient(app).get('/health/ready')
        assert response.status_code == 503
        assert response.json()['error']['code'] == 'SCHEMA_NOT_READY'
    finally:
        app.dependency_overrides.pop(get_runtime, None)
        engine.dispose()


def test_offline_migrations_emit_real_comment_changes_and_restore_json_default():
    from alembic import command
    from alembic.config import Config
    from io import StringIO
    from pathlib import Path

    config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    config.set_main_option('script_location', str(Path(__file__).parents[1] / 'migrations'))
    output = StringIO()
    config.output_buffer = output
    command.upgrade(config, '0005_sync_job_ledger:0006_column_comments', sql=True)
    assert "COMMENT '员工姓名'" in output.getvalue()
    output.seek(0)
    output.truncate(0)
    command.downgrade(config, '0006_column_comments:0005_sync_job_ledger', sql=True)
    assert "DEFAULT ('{}')" in output.getvalue()
    assert "COMMENT '同步任务业务说明'" in output.getvalue()


def test_offline_alignment_changes_database_and_freezes_its_schema():
    from alembic import command
    from alembic.config import Config
    from io import StringIO
    from pathlib import Path
    from sqlalchemy import Column, String

    config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    config.set_main_option('script_location', str(Path(__file__).parents[1] / 'migrations'))
    output = StringIO()
    config.output_buffer = output
    future = Column('future_field', String(64))
    table = Base.metadata.tables['employee']
    table.append_column(future)
    try:
        command.upgrade(config, '0006_column_comments:0007_schema_alignment', sql=True)
    finally:
        table._columns.remove(future)
    sql = output.getvalue()
    assert 'future_field' not in sql
    assert 'ALTER DATABASE' in sql
    assert 'token_digest' not in sql
    assert 'COLLATE utf8mb4_general_ci' in sql


def test_structure_check_detects_missing_index_and_unknown_revision():
    from app.persistence.schema_check import check_schema

    engine, _ = _sessions()
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            connection.execute(text("INSERT INTO alembic_version VALUES ('0009_operation_receipt')"))
        assert check_schema(engine)['errors'] == []
        with engine.begin() as connection:
            connection.execute(text('DROP INDEX ix_admin_session_open_id'))
            connection.execute(text("UPDATE alembic_version SET version_num='unknown'"))
        report = check_schema(engine)
        assert 'schema.version' in report['errors']
        assert 'admin_session.indexes' in report['errors']
    finally:
        engine.dispose()
