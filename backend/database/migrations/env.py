"""
Alembic set-up for the async engine. The database URL comes from
settings.DATABASE_URL (not alembic.ini), and migrations run through
AsyncEngine.run_sync.
"""

import asyncio
import uuid
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from config.settings import settings
from database.session import Base

# Registers every model so autogenerate sees all tables.
import models  # noqa: F401,E402

# Alembic Config object, giving access to the values within alembic.ini.
config = context.config

# Interpret the config file for Python logging, unless it's been
# disabled (e.g. when env.py is imported by test tooling).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Use the app's DATABASE_URL. "%" is escaped for alembic's config parser (URL-encoded passwords).
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))


def run_migrations_offline() -> None:
    """Prints the SQL instead of running it (`alembic upgrade head --sql`)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _bootstrap_empty_database(connection: Connection) -> bool:
    """Empty database (e.g. a new Supabase project): create all tables from the
    models and mark it up to date, since the migrations only alter existing tables.
    Only when there is no `users` table.
    """
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect

    if inspect(connection).has_table("users"):
        # End the transaction inspect() started, or migrations would never commit.
        connection.rollback()
        return False

    target_metadata.create_all(connection)
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.get_context().stamp(ScriptDirectory.from_config(config), "heads")
    # Commit explicitly; alembic won't here.
    connection.commit()
    return True


def _do_run_migrations(connection: Connection) -> None:
    if _bootstrap_empty_database(connection):
        return
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Runs migrations with the async engine."""
    connect_args = {}
    if settings.DATABASE_URL.startswith("postgresql"):
        # Same pooler workaround as config/database.py (no prepared-statement caches, unique names).
        connect_args = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
        }
    connectable = create_async_engine(
        settings.DATABASE_URL, poolclass=pool.NullPool, connect_args=connect_args
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
