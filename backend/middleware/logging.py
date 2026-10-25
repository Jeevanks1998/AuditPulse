"""
One log line per request (method, path, status, time, user). Adds an
X-Request-ID header and request.state.request_id, so an error can be found
in the logs by that id.
"""

import time
import uuid

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from config.logging import logger

REQUEST_ID_HEADER = "X-Request-ID"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        request.state.request_id = request_id

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.bind(request_id=request_id).exception(
                f"{request.method} {request.url.path} -> unhandled exception ({duration_ms}ms)"
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers[REQUEST_ID_HEADER] = request_id

        user_id = getattr(request.state, "user_id", None)
        log_line = (
            f"{request.method} {request.url.path} -> {response.status_code} "
            f"({duration_ms}ms)"
            + (f" user={user_id}" if user_id else "")
        )

        level = "WARNING" if response.status_code >= 400 else "INFO"
        logger.bind(request_id=request_id).log(level, log_line)

        return response


def add_logging_middleware(app: FastAPI) -> None:
    app.add_middleware(RequestLoggingMiddleware)
