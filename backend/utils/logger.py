"""
utils/logger.py

config/logging.py owns *configuring* logging (sinks, format, level —
call `setup_logging()` once at startup, see main.py). This module adds
the small conveniences modules reach for at call sites on top of that
already-configured `logger`, rather than duplicating any of its setup:

  get_logger(name)   - a logger pre-bound with a `module` field, so log
                        lines from e.g. crawler/crawler.py are easy to
                        filter without callers writing f"crawler: {msg}"
                        prefixes by hand (a pattern several existing
                        modules — crawler/screenshots.py,
                        reports/report_storage.py — do manually today).
  log_duration        - decorator, logs how long an async function took
                        and whether it raised.
  log_context(**kv)   - context manager that binds extra fields (e.g.
                        audit_id=123) onto every log line emitted while
                        the block is active.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Iterator, TypeVar

from config.logging import logger as _base_logger

F = TypeVar("F", bound=Callable[..., Any])


def get_logger(name: str):
    """Returns the shared loguru logger pre-bound with `module=name`.

    Usage:
        from utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("crawl finished")   # -> module=<name> in the record
    """
    return _base_logger.bind(module=name)


def log_duration(fn: F) -> F:
    """
    Decorator for async functions: logs entry, exit, elapsed time, and
    re-raises (with a logged warning) on exception. Intended for
    pipeline-stage functions (crawler, each audit module's `run`,
    report generation) where "how long did this take, and did it fail"
    is the recurring question during debugging.
    """
    log = get_logger(getattr(fn, "__module__", "utils.logger"))

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
        except Exception:
            elapsed = time.monotonic() - start
            log.warning(f"{fn.__qualname__} failed after {elapsed:.2f}s")
            raise
        else:
            elapsed = time.monotonic() - start
            log.debug(f"{fn.__qualname__} completed in {elapsed:.2f}s")
            return result

    return wrapper  # type: ignore[return-value]


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """
    Binds extra fields onto every log line emitted inside the block,
    via loguru's contextvar-backed `logger.contextualize`.

        with log_context(audit_id=audit.id, user_id=user.id):
            logger.info("starting SEO checks")   # carries audit_id/user_id
    """
    with _base_logger.contextualize(**fields):
        yield


__all__ = ["get_logger", "log_duration", "log_context"]
