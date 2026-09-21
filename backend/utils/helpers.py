"""
utils/helpers.py

Small, dependency-free (beyond the stdlib) helpers reused across
services/api/crawler modules — the backend counterpart to
assets/js/utils.js's role on the frontend. Nothing here is specific to
any one domain (URLs, files, and formatting each get their own module
alongside this one); these are the leftover generic bits: time,
retries, concurrency, dict/list wrangling, and random tokens.
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
    """Timezone-aware "now", matching the `default=lambda: datetime.now(timezone.utc)`
    pattern already used on every model's `created_at` column."""
    return datetime.now(timezone.utc)


def generate_token(length: int = 32) -> str:
    """URL-safe random token (API keys, share tokens, password reset codes, etc.)."""
    import secrets

    return secrets.token_urlsafe(length)


def chunked(items: Sequence[T], size: int) -> Iterator[List[T]]:
    """Splits `items` into consecutive lists of at most `size` elements.

    Useful for batching crawler/AI-provider calls (e.g. requesting
    recommendations for 50 findings 10 at a time) instead of one call
    per item or one giant call for everything.
    """
    if size <= 0:
        raise ValueError("chunked: size must be positive")
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def safe_get(data: Any, *keys: str, default: Any = None) -> Any:
    """Walks a chain of dict keys, returning `default` the moment any
    level is missing or isn't a dict — avoids a `.get().get().get()`
    chain when reading nested, possibly-partial JSON (API responses
    from PageSpeed, axe-core, provider payloads, etc.)."""
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merges `override` onto a shallow copy of `base`
    (dict-valued keys merge recursively; anything else, `override`
    wins). Used for layering partial settings/preferences updates
    (e.g. api/settings.py PATCH payloads) onto an existing dict without
    clobbering sibling keys the caller didn't send."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def first_or_none(items: Iterable[T]) -> Optional[T]:
    """Returns the first element of an iterable, or None if it's empty —
    reads better than `next(iter(items), None)` at call sites."""
    return next(iter(items), None)


async def retry_async(
    fn: Callable[[], Awaitable[R]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    exceptions: tuple = (Exception,),
) -> R:
    """
    Retries an async callable with exponential backoff + jitter. Meant
    for flaky external calls (PageSpeed/Lighthouse, the AI provider,
    outbound crawler requests) that are worth a couple of retries
    before the surrounding pipeline step gives up on them.

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
    """
    Runs awaitables with at most `limit` in flight at once, preserving
    input order in the returned list. Intended for the crawler's
    per-page fetches (settings.CRAWLER_CONCURRENCY) or any other
    "many small async calls, bounded fan-out" spot, without pulling in
    a task-group library.
    """
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
