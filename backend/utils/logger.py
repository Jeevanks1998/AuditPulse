"""
Logging helpers on top of config/logging.py:
  get_logger(name)  - logger tagged with a module name
  log_duration      - decorator that logs how long an async function took
  log_context(**kv) - adds fields (e.g. audit_id) to every log line in a block
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Iterator, TypeVar

from config.logging import logger as _base_logger

F = TypeVar("F", bound=Callable[..., Any])


def get_logger(name: str):
    """Logger tagged with `module=name`.

        logger = get_logger(__name__)
    """
    return _base_logger.bind(module=name)


def log_duration(fn: F) -> F:
    """Decorator for async functions: logs start, end and time taken, and logs (then re-raises) errors."""
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
    """Adds fields to every log line inside the block.

        with log_context(audit_id=audit.id):
            logger.info("starting")
    """
    with _base_logger.contextualize(**fields):
        yield


__all__ = ["get_logger", "log_duration", "log_context"]
