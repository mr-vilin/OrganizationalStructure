"""真实 MySQL 测试夹具：数据库由部署者提供，各用例以外层事务回滚。"""
import os
import uuid

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.database import create_mysql_engine
from app.persistence.models import DatasetState


@pytest.fixture
def mysql_sessions():
    url = os.environ.get('ORG_TEST_DATABASE_URL')
    if not url:
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
def evaluation_mysql_database():
    """Evaluation 专用独立连接/串行 reset；不改变 mysql_sessions 的回滚语义。"""
    from app.evaluation.fixtures import evaluation_database

    url = os.environ.get('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('未提供 ORG_TEST_DATABASE_URL；Evaluation 真实 MySQL 验收尚未执行')
    with evaluation_database(url) as sessions:
        yield sessions
