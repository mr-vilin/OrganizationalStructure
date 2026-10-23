"""SQLite 测试基础设施：统一连接池、排序规则、外键和单例种子。"""
from sqlalchemy import BigInteger, create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.persistence.models import Base, DatasetState, SystemSetting, WorkerLease


@compiles(BigInteger, 'sqlite')
def sqlite_bigint(element, compiler, **kwargs):
    return 'INTEGER'


def create_sqlite_sessions(*, seed=True, seed_worker_lease=False):
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})

    @event.listens_for(engine, 'connect')
    def configure(connection, _):
        connection.create_collation('utf8mb4_bin', lambda left, right: (left > right) - (left < right))
        connection.execute('PRAGMA foreign_keys=ON')

    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    if seed:
        with sessions.begin() as db:
            db.add(DatasetState(id=1, dataset_epoch='e', data_version=1, initialization_status='complete'))
            db.add(SystemSetting(key='task_queue_lock', value='1'))
            if seed_worker_lease:
                db.add(WorkerLease(id=1, generation=0))
    return engine, sessions
