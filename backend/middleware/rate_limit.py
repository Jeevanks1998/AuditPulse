"""
Request limits per time window. Uses Redis so every process shares the count;
falls back to memory if Redis is down. Counted per user when known,
otherwise per IP. /auth/* has a stricter limit.
"""

import time
from typing import Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from config.logging import logger
from config.settings import settings

AUTH_PATH_PREFIX = f"{settings.API_V1_PREFIX}/auth"

# Redis client, created on first use. A bad REDIS_URL falls back to memory; it never stops start-up.
_redis_client: Optional[aioredis.Redis] = None
_redis_unavailable = False  # stays True after one failure, so we don't retry on every request

# Memory fallback: {key: (window_start, count)}
_memory_counters: dict[str, tuple[int, int]] = {}


def _get_redis() -> Optional[aioredis.Redis]:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
        )
    return _redis_client


async def _increment(scope_key: str, window_seconds: int) -> int:
    """Adds one to this window's count (Redis or memory) and returns it."""
    global _redis_unavailable

    now = int(time.time())
    window_start = now - (now % window_seconds)
    redis_key = f"ratelimit:{scope_key}:{window_start}"

    if not _redis_unavailable:
        try:
            client = _get_redis()
            count = await client.incr(redis_key)
            if count == 1:
                await client.expire(redis_key, window_seconds)
            return count
        except Exception as exc:  # noqa: BLE001
            _redis_unavailable = True
            logger.warning(f"rate_limit: Redis unavailable, falling back to in-memory limiting: {exc}")

    # Memory fallback
    stored_window, count = _memory_counters.get(scope_key, (window_start, 0))
    if stored_window != window_start:
        count = 0
    count += 1
    _memory_counters[scope_key] = (window_start, count)
    return count


def _scope_for(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    return f"user:{user_id}" if user_id else f"ip:{request.client.host if request.client else 'unknown'}"


def _limits_for(path: str) -> tuple[int, int]:
    if path.startswith(AUTH_PATH_PREFIX):
        return settings.RATE_LIMIT_AUTH_REQUESTS, settings.RATE_LIMIT_AUTH_WINDOW_SECONDS
    return settings.RATE_LIMIT_REQUESTS, settings.RATE_LIMIT_WINDOW_SECONDS


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        # Screenshots are never limited: one report loads dozens at once.
        if not settings.RATE_LIMIT_ENABLED or request.url.path.startswith("/screenshots/") or any(
            request.url.path.startswith(p) for p in settings.RATE_LIMIT_EXEMPT_PATHS
        ):
            return await call_next(request)

        limit, window = _limits_for(request.url.path)
        scope_key = f"{_scope_for(request)}:{'auth' if request.url.path.startswith(AUTH_PATH_PREFIX) else 'api'}"
        count = await _increment(scope_key, window)
        remaining = max(limit - count, 0)

        if count > limit:
            retry_after = window - (int(time.time()) % window)
            logger.warning(f"rate_limit: {scope_key} exceeded {limit}/{window}s on {request.url.path}")
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": "Rate limit exceeded. Please slow down and try again shortly.",
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


def add_rate_limit_middleware(app: FastAPI) -> None:
    app.add_middleware(RateLimitMiddleware)
