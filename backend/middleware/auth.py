"""
Works out who is calling (Bearer token or X-API-Key) before routing, and puts
it on request.state for logging and rate limits. Never rejects a request;
routes still enforce auth with get_current_user.
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

        # Only real sessions, not sign-in challenge tokens.
        if payload.get("typ") != "access":
            return None

        subject = payload.get("sub")
        try:
            return int(subject) if subject is not None else None
        except (TypeError, ValueError):
            return None

    async def _resolve_from_api_key(self, request: Request) -> Optional[int]:
        api_key = request.headers.get(API_KEY_HEADER)
        if not api_key:
            return None

        # Own short session: middleware runs before any route's get_db.
        try:
            from models.user import User  # local import avoids a cycle at start-up

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(User.id).where(
                        User.api_key == api_key,
                        User.is_active.is_(True),
                        User.auditpulse_access.is_(True),
                    )
                )
                row = result.first()
                return row[0] if row else None
        except Exception as exc:  # noqa: BLE001 — context resolution is best-effort, never blocks the request
            logger.warning(f"AuthContextMiddleware: API key lookup failed: {exc}")
            return None


def add_auth_context_middleware(app: FastAPI) -> None:
    app.add_middleware(AuthContextMiddleware)
