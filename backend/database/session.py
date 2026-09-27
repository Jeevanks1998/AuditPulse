"""
database/session.py

Backend-facing home for DB session concerns, layered on top of
config/database.py, which owns the actual async engine and
sessionmaker (there is exactly one of each per process — this module
re-exports them rather than building a second one).

config/database.py's `get_db` is a FastAPI dependency: it only makes
sense inside a request, where FastAPI drives the generator's lifecycle.
Background code has no request to hang that off — workers/audit_worker.py
and scheduler/jobs.py currently each open `AsyncSessionLocal()` directly
and manage commit/rollback by hand around every task. `session_scope()`
below is that same pattern, written once:

    from database.session import session_scope

    async def run_job():
        async with session_scope() as db:
            audit = await db.get(Audit, audit_id)
            audit.status = "completed"
            # commits automatically on clean exit, rolls back + re-raises
            # on any exception, and always closes the session

New background/CLI code (database/seed.py included) should prefer this
over opening AsyncSessionLocal() directly.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from config.database import (
    AsyncSessionLocal,
    Base,
    close_db,
    engine,
    get_db,
    init_db,
)
from config.logging import logger


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """
    Commit-on-success / rollback-on-exception async context manager for
    a request-independent DB session. Always closes the session on the
    way out, whichever path it takes.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("database.session: session_scope rolled back on exception")
            raise
        finally:
            await session.close()


__all__ = [
    "Base",
    "engine",
    "AsyncSessionLocal",
    "get_db",
    "init_db",
    "close_db",
    "session_scope",
]
