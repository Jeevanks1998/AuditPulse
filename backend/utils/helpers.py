"""
Small general helpers: time, tokens, batching, nested dicts, retries and limited concurrency.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Iterator, List, Optional, Sequence, TypeVar

from utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")
R = TypeVar("R")


def utc_now() -> datetime:
    """Timezone-aware current time (UTC)."""
    return datetime.now(timezone.utc)


def generate_token(length: int = 32) -> str:
    """Random URL-safe token (API keys, share links...)."""
    import secrets

    return secrets.token_urlsafe(length)


def chunked(items: Sequence[T], size: int) -> Iterator[List[T]]:
    """Splits `items` into lists of at most `size`."""
    if size <= 0:
        raise ValueError("chunked: size must be positive")
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def safe_get(data: Any, *keys: str, default: Any = None) -> Any:
    """Reads nested dict keys safely; returns `default` if any level is missing."""
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def deep_merge(base: dict, override: dict) -> dict:
    """Merges `override` into a copy of `base`, recursing into nested dicts."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def first_or_none(items: Iterable[T]) -> Optional[T]:
    """First item, or None if empty."""
    return next(iter(items), None)


async def retry_async(
    fn: Callable[[], Awaitable[R]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    exceptions: tuple = (Exception,),
) -> R:
    """Retries an async call with exponential backoff, for flaky external calls.

        result = await retry_async(lambda: client.get(url), attempts=3)
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except exceptions as exc:  # noqa: BLE001 - intentionally broad, caller narrows via `exceptions`
            last_exc = exc
            if attempt == attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt - 1))) + random.uniform(0, 0.25)
            logger.warning(f"retry_async: attempt {attempt}/{attempts} failed ({exc!r}), retrying in {delay:.2f}s")
            await asyncio.sleep(delay)

    assert last_exc is not None  # attempts >= 1 guarantees this
    raise last_exc


async def run_concurrently(
    coros: Sequence[Awaitable[R]],
    limit: int,
) -> List[R]:
    """Runs awaitables with at most `limit` at once, keeping the input order."""
    semaphore = asyncio.Semaphore(limit)

    async def _run(coro: Awaitable[R]) -> R:
        async with semaphore:
            return await coro

    return await asyncio.gather(*(_run(c) for c in coros))


__all__ = [
    "utc_now",
    "generate_token",
    "chunked",
    "safe_get",
    "deep_merge",
    "first_or_none",
    "retry_async",
    "run_concurrently",
]
