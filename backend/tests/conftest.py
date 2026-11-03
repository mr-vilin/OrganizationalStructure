import pytest

from db_fixtures import create_sqlite_sessions


def pytest_addoption(parser):
    parser.addoption(
        '--require-mysql',
        action='store_true',
        default=False,
        help='集成测试未配置独立 MySQL 时失败，而不是跳过',
    )


@pytest.fixture
def sqlite_sessions():
    engine, sessions = create_sqlite_sessions()
    try:
        yield sessions
    finally:
        engine.dispose()
