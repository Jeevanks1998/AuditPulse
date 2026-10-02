"""
database/migrations/env.py

Alembic environment for the async SQLAlchemy engine configured in
config/database.py. Two things differ from the default `alembic init`
template because this project is async end-to-end:

  1. The connection string comes from config.settings.settings
     (DATABASE_URL), not alembic.ini's `sqlalchemy.url` — one source of
     truth for the connection string, same as the app itself uses.
  2. `run_migrations_online` runs the sync migration function via
     `AsyncEngine.run_sync`, since Alembic's migration machinery is
     itself synchronous and asyncpg's engine is not.

`target_metadata` is `database.session.Base.metadata` after importing
`models` (mirrors main.py's own `import models  # noqa: F401`), so
`alembic revision --autogenerate` sees every table.
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

# Registers every ORM model on Base.metadata before autogenerate runs.
import models  # noqa: F401,E402

# Alembic Config object, giving access to the values within alembic.ini.
config = context.config

# Interpret the config file for Python logging, unless it's been
# disabled (e.g. when env.py is imported by test tooling).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override alembic.ini's sqlalchemy.url with the app's real setting so
# the two never drift.
# "%" is escaped because alembic's config is a ConfigParser: a URL-encoded
# Supabase password (e.g. p%40ss) would otherwise raise an interpolation error.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))


def run_migrations_offline() -> None:
    """
    Emit SQL to stdout without a live DB connection (`alembic upgrade
    head --sql`). Useful for reviewing generated SQL or for DBs that
    require a DBA to run migrations by hand.
    """
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
    """Brand-new database (e.g. a fresh Supabase project): create every
    table straight from the models and mark it as up to date.

    The migration chain in versions/ only *alters* tables that the app
    used to create itself on startup, so running it against an empty
    database fails ("relation ... does not exist") — and Railway runs
    `alembic upgrade head` before the app ever starts. The models are the
    current schema, so create_all + stamp head gives exactly the same
    result as an existing database after all migrations.

    Only fires when there is no `users` table at all; any existing
    database goes through the normal migrations below.
    """
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect

    if inspect(connection).has_table("users"):
        # inspect() auto-began a transaction. End it, or alembic would run
        # the migrations inside it and never commit them.
        connection.rollback()
        return False

    target_metadata.create_all(connection)
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.get_context().stamp(ScriptDirectory.from_config(config), "heads")
    # create_all() auto-began the transaction, so alembic won't commit it
    # for us here — commit explicitly.
    connection.commit()
    return True


def _do_run_migrations(connection: Connection) -> None:
    if _bootstrap_empty_database(connection):
        return
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connects with the real async engine and runs migrations against it."""
    connect_args = {}
    if settings.DATABASE_URL.startswith("postgresql"):
        # Same PgBouncer-transaction-pooler workaround as config/database.py:
        # disable both of asyncpg's prepared-statement caches and give every
        # statement a unique name, so migrations don't hit
        # "prepared statement ... already exists" against a pooled DATABASE_URL.
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
