import os

from alembic import context
from app.persistence.database import create_mysql_engine

from app.persistence.models import Base


config = context.config
database_url = os.getenv("ORG_DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.execute("SET NAMES utf8mb4 COLLATE utf8mb4_general_ci")
        context.execute("SET time_zone = '+00:00'")
        context.run_migrations()


def run_migrations_online():
    connectable = create_mysql_engine(config.get_main_option("sqlalchemy.url"))
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()

