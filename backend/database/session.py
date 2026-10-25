"""
session_scope(): database session for code outside a request (workers,
scheduler, scripts). Commits on success, rolls back on error, always closes.

    async with session_scope() as db:
        ...
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
    """Commits on success, rolls back on error, always closes the session."""
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
