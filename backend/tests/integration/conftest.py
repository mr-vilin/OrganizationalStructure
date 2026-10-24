"""真实 MySQL 测试夹具：数据库由部署者提供，各用例以外层事务回滚。"""
import os
from pathlib import Path
import uuid

from alembic.config import Config
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.database import create_mysql_engine
from app.persistence.models import DatasetState


@pytest.fixture
def mysql_sessions(request):
    url = os.environ.get('ORG_TEST_DATABASE_URL')
    if not url:
        if request.config.getoption('--require-mysql'):
            pytest.fail('未提供 ORG_TEST_DATABASE_URL；--require-mysql 要求真实 MySQL 验收')
        pytest.skip('未提供 ORG_TEST_DATABASE_URL；真实 MySQL 验收尚未执行')
    parsed = make_url(url)
    if parsed.drivername != 'mysql+pymysql' or not (parsed.database or '').endswith('_test'):
        pytest.fail('集成测试仅允许 mysql+pymysql 且数据库名以 _test 结尾的独立测试库')
    engine = create_mysql_engine(url)

    class IntegrationSession(Session):
        pass

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            sessions = sessionmaker(bind=connection, class_=IntegrationSession, expire_on_commit=False, join_transaction_mode='create_savepoint')
            try:
                with sessions.begin() as db:
                    state = db.get(DatasetState, 1)
                    if state is None:
                        pytest.fail('请先对独立测试库执行 alembic upgrade head')
                    state.dataset_epoch = 'test-' + uuid.uuid4().hex
                    state.data_version = 1
                    state.initialization_status = 'complete'
                yield sessions
            finally:
                if transaction.is_active:
                    transaction.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def migration_database(request, monkeypatch):
    source = os.getenv('ORG_MIGRATION_TEST_DATABASE_URL')
    if not source:
        if request.config.getoption('--require-mysql'):
            pytest.fail('未提供 ORG_MIGRATION_TEST_DATABASE_URL；--require-mysql 要求迁移演练')
        pytest.skip('未提供 ORG_MIGRATION_TEST_DATABASE_URL；MySQL 迁移演练未执行')
    url = make_url(source)
    if url.drivername != 'mysql+pymysql' or url.host not in {'127.0.0.1', 'localhost'} or not (url.database or '').endswith('_test'):
        pytest.fail('迁移演练只允许本机、库名以 _test 结尾的独立 MySQL 实例')
    admin = create_mysql_engine(source)
    name = 'tmp_org_' + uuid.uuid4().hex[:12] + '_test'
    created = False
    engine = None
    try:
        with admin.connect() as connection:
            assert connection.execute(text('SELECT VERSION()')).scalar_one().startswith('8.4.')
            connection.execute(text(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs'))
            created = True
        target = url.set(database=name).render_as_string(hide_password=False)
        # env.py 优先读取此变量；必须覆盖外部连接，确保迁移只写随机测试库。
        monkeypatch.setenv('ORG_DATABASE_URL', target)
        engine = create_mysql_engine(target)
        config = Config(str(Path(__file__).parents[2] / 'alembic.ini'))
        config.set_main_option('script_location', str(Path(__file__).parents[2] / 'migrations'))
        yield engine, config
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE `{name}`'))
        admin.dispose()
