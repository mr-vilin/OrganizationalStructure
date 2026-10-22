from collections.abc import Iterator

from dataclasses import dataclass

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from .models import Base


CURRENT_SCHEMA_HEAD = "0008_session_digest"
REQUIRED_COLUMNS = {table.name: set(table.columns.keys()) for table in Base.metadata.tables.values()}


@dataclass(frozen=True)
class DatabaseReadinessError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def create_mysql_engine(database_url: str) -> Engine:
    if not database_url.startswith("mysql+pymysql://"):
        raise ValueError("ORG_DATABASE_URL must use mysql+pymysql")
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        isolation_level="REPEATABLE READ",
        hide_parameters=True,
        connect_args={"charset": "utf8mb4"},
    )

    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def configure_session(connection, _):
        cursor = connection.cursor()
        try:
            cursor.execute("SET NAMES utf8mb4 COLLATE utf8mb4_general_ci")
            cursor.execute("SET time_zone = '+00:00'")
        finally:
            cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def database_ready(engine: Engine, expected_head: str = CURRENT_SCHEMA_HEAD) -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        if "alembic_version" not in tables:
            raise DatabaseReadinessError("SCHEMA_NOT_READY", "数据库缺少迁移版本表")
        versions = [row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))]
        if versions != [expected_head]:
            raise DatabaseReadinessError("SCHEMA_NOT_READY", "数据库迁移版本不是当前构建支持的版本")

        missing_tables = sorted(set(REQUIRED_COLUMNS) - tables)
        if missing_tables:
            raise DatabaseReadinessError("SCHEMA_NOT_READY", "数据库缺少必要业务表")
        for table, required in REQUIRED_COLUMNS.items():
            columns = {column["name"] for column in inspector.get_columns(table)}
            if required - columns:
                raise DatabaseReadinessError("SCHEMA_NOT_READY", "数据库缺少必要字段")
        for query in (
            "SELECT dataset_epoch, data_version, initialization_status FROM dataset_state WHERE id = 1",
            "SELECT generation FROM worker_lease WHERE id = 1",
            "SELECT value FROM system_setting WHERE `key` = 'task_queue_lock'",
        ):
            if connection.execute(text(query)).first() is None:
                raise DatabaseReadinessError("SCHEMA_NOT_READY", "数据库缺少必要单例记录")
    return {"database": "ready", "schema": "ready"}


def schema_snapshot(engine: Engine) -> dict:
    """只读采集迁移版本和业务结构，供审查与执行前后对比使用。"""
    with engine.connect() as connection:
        inspector = inspect(connection)
        names = set(inspector.get_table_names())
        versions = [row[0] for row in connection.execute(text("SELECT version_num FROM alembic_version"))] if 'alembic_version' in names else []
        database = {}
        session = {}
        mysql_columns = {}
        mysql_tables = {}
        mysql_indexes = {}
        if engine.dialect.name == 'mysql':
            database = dict(connection.execute(text('''
                SELECT DEFAULT_CHARACTER_SET_NAME AS charset, DEFAULT_COLLATION_NAME AS collation
                FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = DATABASE()
            ''')).mappings().one())
            session = dict(connection.execute(text('''
                SELECT VERSION() AS version, @@character_set_client AS character_set_client,
                       @@character_set_connection AS character_set_connection,
                       @@character_set_results AS character_set_results,
                       @@collation_connection AS collation_connection,
                       @@time_zone AS time_zone, @@transaction_isolation AS transaction_isolation
            ''')).mappings().one())
            mysql_columns = {(row['TABLE_NAME'], row['COLUMN_NAME']): dict(row) for row in connection.execute(text('''
                SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLUMN_DEFAULT, EXTRA,
                       CHARACTER_SET_NAME, COLLATION_NAME, GENERATION_EXPRESSION
                FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
            ''')).mappings()}
            mysql_tables = {row['TABLE_NAME']: {'engine': row['ENGINE'], 'collation': row['TABLE_COLLATION']}
                            for row in connection.execute(text('''
                SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
            ''')).mappings()}
            for row in connection.execute(text('''
                SELECT TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME, NON_UNIQUE,
                       SUB_PART, COLLATION, INDEX_TYPE, IS_VISIBLE, EXPRESSION
                FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
            ''')).mappings():
                mysql_indexes.setdefault(row['TABLE_NAME'], []).append(dict(row))
        tables = {}
        for table in sorted(names - {"alembic_version"}):
            columns = []
            for column in inspector.get_columns(table):
                column_type = column["type"]
                actual = mysql_columns.get((table, column['name']), {})
                columns.append({
                    "name": column["name"],
                    "type": actual.get('COLUMN_TYPE', str(column_type)),
                    "nullable": bool(column["nullable"]),
                    "default": actual.get('COLUMN_DEFAULT', column.get("default")),
                    "comment": column.get("comment"),
                    "collation": actual.get('COLLATION_NAME', getattr(column_type, "collation", None)),
                    "charset": actual.get('CHARACTER_SET_NAME'),
                    "autoincrement": 'auto_increment' in actual.get('EXTRA', '') if actual else column.get('autoincrement'),
                    "computed": actual.get('GENERATION_EXPRESSION') or column.get('computed'),
                    "extra": actual.get('EXTRA'),
                })
            try:
                comment = inspector.get_table_comment(table).get("text")
            except (NotImplementedError, AttributeError):
                comment = None
            tables[table] = {
                "options": mysql_tables.get(table, {}),
                "index_metadata": mysql_indexes.get(table, []),
                "comment": comment,
                "columns": columns,
                "primary_key": inspector.get_pk_constraint(table),
                "foreign_keys": inspector.get_foreign_keys(table),
                "unique_constraints": inspector.get_unique_constraints(table),
                "indexes": inspector.get_indexes(table),
            }
    return {"versions": versions, "database": database, "session": session, "tables": tables}
