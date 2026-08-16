"""
middleware/auth.py

api/auth.py's `get_current_user` dependency is still what actually
*enforces* authentication on a route — that stays exactly as it is.
What's missing is a way for the rest of the app (middleware/logging.py's
per-request log line, middleware/rate_limit.py's per-user bucket) to
know who's calling *before* a route's dependencies have even run, and a
second entry point for the API key every account already has
(models.user.User.api_key, generated in api/auth.py and shown/rotated on
settings.html) — right now nothing accepts that key anywhere; the only
working auth path is the Bearer JWT the frontend's own login flow
issues.

AuthContextMiddleware fills both gaps: it best-effort resolves either an
`Authorization: Bearer <jwt>` header or an `X-API-Key: <key>` header to
a user id and stamps it (plus which method matched) onto
`request.state`, before the request reaches routing. It never rejects a
request itself — an invalid/missing credential just leaves
`request.state.user_id` as None, and routes that require auth still get
that enforcement from `get_current_user` exactly as before. That split
keeps this middleware safe to add without touching a single route's
behavior.
"""

from typing import Optional

from fastapi import FastAPI, Request
from jose import JWTError, jwt
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from config.database import AsyncSessionLocal
from config.logging import logger
from config.settings import settings

API_KEY_HEADER = "X-API-Key"


class AuthContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request.state.user_id = None
        request.state.auth_method = None

        user_id = await self._resolve_from_bearer(request)
        method = "jwt" if user_id else None

        if user_id is None:
            user_id = await self._resolve_from_api_key(request)
            method = "api_key" if user_id else None

        request.state.user_id = user_id
        request.state.auth_method = method

        return await call_next(request)

    # ----------------------------------------------------------------
    async def _resolve_from_bearer(self, request: Request) -> Optional[int]:
        authorization = request.headers.get("Authorization", "")
        if not authorization.lower().startswith("bearer "):
            return None
        token = authorization.split(" ", 1)[1].strip()
        if not token:
            return None

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        except JWTError:
            return None

        subject = payload.get("sub")
        try:
            return int(subject) if subject is not None else None
        except (TypeError, ValueError):
            return None

    # ----------------------------------------------------------------
    async def _resolve_from_api_key(self, request: Request) -> Optional[int]:
        api_key = request.headers.get(API_KEY_HEADER)
        if not api_key:
            return None

        # Own short-lived session — middleware runs ahead of any route's
        # `Depends(get_db)`, so there's no request-scoped session to reuse
        # yet (see config/database.py's docstring on that rule).
        try:
            from models.user import User  # local import avoids a module cycle at app start-up

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(User.id).where(User.api_key == api_key, User.is_active.is_(True))
                )
                row = result.first()
                return row[0] if row else None
        except Exception as exc:  # noqa: BLE001 — context resolution is best-effort, never blocks the request
            logger.warning(f"AuthContextMiddleware: API key lookup failed: {exc}")
            return None


def add_auth_context_middleware(app: FastAPI) -> None:
    app.add_middleware(AuthContextMiddleware)
