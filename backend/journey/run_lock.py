"""
One-at-a-time slots, shared by every process in the container (file locks;
no-op on Windows). Two browsers at once can run the small server out of
memory and make both runs fail.
  audit_slot   - one audit at a time; the others wait as "queued"
  journey_slot - one Journey Map browser at a time
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from config.logging import logger

try:  # Linux/Docker only
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

LOCK_PATH = os.path.join(tempfile.gettempdir(), "auditpulse-journey.lock")
AUDIT_LOCK_PATH = os.path.join(tempfile.gettempdir(), "auditpulse-audit.lock")


def journey_slot(max_wait_s: float, poll_s: float = 2.0):
    """Waits up to max_wait_s for another journey scan to finish; then goes ahead anyway. Yields the seconds waited."""
    return _slot(LOCK_PATH, "journey scan", max_wait_s, poll_s)


def audit_slot(max_wait_s: float, poll_s: float = 3.0):
    """Waits up to max_wait_s for the running audit to finish; then goes ahead anyway. Yields the seconds waited."""
    return _slot(AUDIT_LOCK_PATH, "audit", max_wait_s, poll_s)


@asynccontextmanager
async def _slot(path: str, what: str, max_wait_s: float, poll_s: float) -> AsyncIterator[float]:
    started = time.monotonic()
    if fcntl is None:
        yield 0.0
        return
    fh = open(path, "a+")
    locked = False
    try:
        logged = False
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if not logged:
                    logger.info(f"another {what} is running — waiting for it to finish")
                    logged = True
                if time.monotonic() - started >= max_wait_s:
                    logger.warning(f"waited {max_wait_s:.0f}s for the other {what}; starting anyway")
                    break
                await asyncio.sleep(poll_s)
        yield time.monotonic() - started
    finally:
        if locked:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        fh.close()
