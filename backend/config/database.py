"""
Async database engine and sessions. Routes use `get_db` for a per-request session.
"""

import asyncio
import uuid
from typing import AsyncGenerator, Coroutine, TypeVar

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

_T = TypeVar("_T")

from config.logging import logger
from config.settings import settings


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


_engine_kwargs = {"echo": settings.DB_ECHO, "pool_pre_ping": True}
if settings.DATABASE_URL.startswith("postgresql"):
    # Supabase's transaction pooler (port 6543) gives each transaction a different
    # connection, which breaks asyncpg's prepared-statement caches. So: turn both
    # caches off, give statements random names, and use NullPool (the pooler
    # does the pooling).
    _engine_kwargs["poolclass"] = NullPool
    _engine_kwargs["connect_args"] = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
    }
elif not settings.DATABASE_URL.startswith("sqlite"):
    # SQLite doesn't accept pool sizes.
    _engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
    _engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Request-scoped database session (FastAPI dependency)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Creates tables at startup for local development. Use Alembic migrations elsewhere."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified/created")


async def close_db() -> None:
    """Closes the connection pool at shutdown."""
    await engine.dispose()
    logger.info("Database connections closed")


def run_async(coro: Coroutine[None, None, _T]) -> _T:
    """Runs a coroutine in its own event loop, for Celery tasks. Use this instead of
    asyncio.run() in tasks that touch the database: it closes the pool before the
    loop ends, otherwise the next task fails with "Event loop is closed".
    """

    async def _wrapped() -> _T:
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(_wrapped())
