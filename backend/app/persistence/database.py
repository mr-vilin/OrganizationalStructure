from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_mysql_engine(database_url: str) -> Engine:
    if not database_url.startswith("mysql+pymysql://"):
        raise ValueError("ORG_DATABASE_URL must use mysql+pymysql")
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=1800, isolation_level="REPEATABLE READ", hide_parameters=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def database_ready(engine: Engine) -> bool:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    return True
