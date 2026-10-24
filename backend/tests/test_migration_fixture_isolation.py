"""无需数据库即可验证迁移夹具覆盖外部连接，并在结束后恢复环境。"""
from io import StringIO
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

from alembic import command
import pytest
from sqlalchemy.engine import make_url


@pytest.mark.parametrize('previous_url', [None, 'mysql+pymysql://unused:unused@localhost/business'])
def test_migrations_use_random_test_database_and_restore_environment(monkeypatch, previous_url):
    from integration import conftest as mysql_fixtures

    if previous_url is None:
        monkeypatch.delenv('ORG_DATABASE_URL', raising=False)
    else:
        monkeypatch.setenv('ORG_DATABASE_URL', previous_url)
    monkeypatch.setenv(
        'ORG_MIGRATION_TEST_DATABASE_URL',
        'mysql+pymysql://unused:unused@localhost/isolated_test',
    )
    admin = MagicMock()
    connection = admin.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.return_value = '8.4.11'
    target_engine = MagicMock()
    factory = MagicMock(side_effect=[admin, target_engine])
    monkeypatch.setattr(mysql_fixtures, 'create_mysql_engine', factory)
    request = SimpleNamespace(config=SimpleNamespace(getoption=lambda _: True))

    with monkeypatch.context() as scoped:
        fixture = mysql_fixtures.migration_database.__wrapped__(request, scoped)
        engine, config = next(fixture)
        try:
            target_url = factory.call_args_list[1].args[0]
            database = make_url(target_url).database
            assert database.startswith('tmp_org_') and database.endswith('_test')
            assert database != 'isolated_test'
            assert engine is target_engine
            config.output_buffer = StringIO()
            # 执行真实 env.py 的离线路径，确认 Alembic 最终选用随机库。
            command.upgrade(config, 'head', sql=True)
            assert config.get_main_option('sqlalchemy.url') == target_url
        finally:
            fixture.close()

    assert os.getenv('ORG_DATABASE_URL') == previous_url
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert any(sql.startswith(f'CREATE DATABASE `{database}`') for sql in statements)
    assert statements[-1] == f'DROP DATABASE `{database}`'
    target_engine.dispose.assert_called_once()
    admin.dispose.assert_called_once()
