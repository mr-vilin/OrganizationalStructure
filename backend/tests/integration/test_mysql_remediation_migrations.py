"""仅对显式提供的独立 MySQL 8.4 测试实例创建可丢弃随机库。"""
from io import StringIO
import hashlib

from alembic import command
import pytest
from sqlalchemy import event, text

from app.persistence.database import database_ready, schema_snapshot, session_factory
from app.persistence.repositories import SqlIdentityRepository
from app.persistence.schema_check import check_schema


def test_mysql_comment_roundtrip_and_full_alignment(migration_database):
    engine, config = migration_database
    command.upgrade(config, '0005_sync_job_ledger')
    before = schema_snapshot(engine)
    command.upgrade(config, '0006_column_comments')
    command.downgrade(config, '0005_sync_job_ledger')
    assert schema_snapshot(engine) == before
    command.upgrade(config, 'head')
    assert check_schema(engine)['errors'] == []
    assert database_ready(engine)['schema'] == 'ready'
    engine.dispose()  # 强制重连，验证新连接同样配置会话参数。
    assert check_schema(engine)['errors'] == []


@pytest.mark.parametrize('checkpoint', ['ADD COLUMN token_digest', 'MODIFY token_digest', 'CREATE UNIQUE INDEX'])
def test_mysql_session_migration_retry_revokes_old_tokens(migration_database, checkpoint):
    from datetime import datetime

    engine, config = migration_database
    command.upgrade(config, '0007_schema_alignment')
    legacy_token = 'synthetic-legacy-cookie-for-migration'
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO admin_allowlist(open_id, created_at) VALUES ('ou_test', UTC_TIMESTAMP())"))
        connection.execute(text('''INSERT INTO admin_session(id, open_id, csrf_hash, expires_at)
            VALUES (:token, 'ou_test', 'synthetic-csrf', '2099-01-01')'''), {'token': legacy_token})
    # 在已提交 DDL 之后失败，再使用原迁移重跑，覆盖 MySQL DDL 隐式提交边界。
    def interrupt(connection, cursor, statement, parameters, context, executemany):
        if checkpoint in statement:
            raise RuntimeError('injected migration interruption')
    from sqlalchemy.engine import Engine
    event.listen(Engine, 'after_cursor_execute', interrupt)
    try:
        with pytest.raises(RuntimeError, match='injected migration interruption'):
            command.upgrade(config, 'head')
    finally:
        event.remove(Engine, 'after_cursor_execute', interrupt)
    command.upgrade(config, 'head')
    assert check_schema(engine)['errors'] == []
    with engine.connect() as connection:
        rows = connection.execute(text('SELECT id, token_digest, revoked_at FROM admin_session')).all()
        assert len(rows) == 1
        assert rows[0].id != legacy_token
        assert rows[0].token_digest == hashlib.sha256(legacy_token.encode()).hexdigest()
        assert rows[0].revoked_at is not None
    repository = SqlIdentityRepository(session_factory(engine), 's' * 32)
    assert repository.authenticate_session(legacy_token, datetime.utcnow()) is None
    assert repository.authenticate_session(rows[0].token_digest, datetime.utcnow()) is None


def test_mysql_collation_conflict_stops_before_any_alignment_ddl(migration_database):
    engine, config = migration_database
    command.upgrade(config, '0006_column_comments')
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO pending_fact(object_type,source_id,normalized_data,error_code,updated_at) VALUES ('type','same','{}','test',UTC_TIMESTAMP()), ('type ','same','{}','test',UTC_TIMESTAMP())"))
    before = schema_snapshot(engine)
    with pytest.raises(RuntimeError, match='唯一键冲突'):
        command.upgrade(config, '0007_schema_alignment')
    assert schema_snapshot(engine) == before


def test_mysql_offline_new_database_matches_online_target(migration_database):
    engine, config = migration_database
    output = StringIO()
    config.output_buffer = output
    command.upgrade(config, 'head', sql=True)
    # 本项目迁移无存储过程或含分号的字面值，按语句执行生成包。
    with engine.begin() as connection:
        for statement in output.getvalue().split(';'):
            if statement.strip():
                connection.exec_driver_sql(statement)
    assert check_schema(engine)['errors'] == []


def test_mysql_schema_check_rejects_prefix_unique_index(migration_database):
    engine, config = migration_database
    command.upgrade(config, 'head')
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE admin_session DROP INDEX uq_admin_session_token_digest, ADD UNIQUE INDEX uq_admin_session_token_digest(token_digest(16))'))
    assert 'admin_session.index_definition.uq_admin_session_token_digest' in check_schema(engine)['errors']
