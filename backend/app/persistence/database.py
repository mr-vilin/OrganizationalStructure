from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_mysql_engine(database_url: str) -> Engine:
    if not database_url.startswith("mysql+pymysql://"):
        raise ValueError("ORG_DATABASE_URL must use mysql+pymysql")
    engine = create_engine(
        database_url, pool_pre_ping=True, pool_recycle=1800,
        isolation_level="REPEATABLE READ", hide_parameters=True,
        connect_args={"charset": "utf8mb4", "collation": "utf8mb4_0900_as_cs"},
    )
    # SQLAlchemy 的 MySQL 方言先执行 SET NAMES charset，覆盖驱动传入的
    # collation；在其 connect 初始化之后恢复项目的显式会话约定。
    def configure_charset(connection, _record):
        connection.set_character_set("utf8mb4", "utf8mb4_0900_as_cs")

    event.listen(engine, "connect", configure_charset)
    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def database_ready(engine: Engine) -> bool:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    return True
