"""
config/database.py

Async SQLAlchemy engine + session management. Models (in a future
`models/` package) should inherit from `Base`. Routes/services should
depend on `get_db` to obtain a request-scoped AsyncSession.
"""

import asyncio
from typing import AsyncGenerator, Coroutine, TypeVar

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

_T = TypeVar("_T")

from config.logging import logger
from config.settings import settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


_engine_kwargs = {"echo": settings.DB_ECHO, "pool_pre_ping": True}
if not settings.DATABASE_URL.startswith("sqlite"):
    # SQLite's async driver uses NullPool and doesn't accept pool sizing args.
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
    """FastAPI dependency: yields a request-scoped DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Create tables on startup for local/dev use.
    In staging/production, prefer Alembic migrations instead of this.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified/created")


async def close_db() -> None:
    """Dispose of the engine's connection pool on shutdown."""
    await engine.dispose()
    logger.info("Database connections closed")


def run_async(coro: Coroutine[None, None, _T]) -> _T:
    """Run a coroutine in its own event loop, for Celery tasks.

    Celery tasks are synchronous, so every task entry point (scheduler/jobs.py,
    scheduler/reminders.py, workers/audit_worker.py, workers/report_worker.py)
    wraps its async body in `asyncio.run(...)`. That gives each task run a
    brand-new event loop — but `engine`/`AsyncSessionLocal` above are created
    once at process import time and share a single asyncpg connection pool
    across every task run in the worker process.

    asyncpg connections are bound to the event loop they were opened on.
    When `asyncio.run()` closes its loop at the end of a task, any pooled
    connection is left attached to a now-dead loop. The *next* task's
    `asyncio.run()` creates a different loop and blows up trying to reuse
    that connection ("Event loop is closed" / "got Future ... attached to
    a different loop").

    Disposing the pool here — still inside the same loop, right before it
    closes — closes every connection cleanly so the pool starts empty next
    time, and the next task opens fresh connections bound to its own loop.
    Use this instead of calling `asyncio.run()` directly in any task that
    touches the database.
    """

    async def _wrapped() -> _T:
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(_wrapped())
