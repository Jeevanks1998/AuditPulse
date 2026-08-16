"""
middleware/logging.py

One log line per request, through the same loguru sink
config/logging.py already sets up (so these lines get the identical
format/rotation/file-and-stdout routing as everything else the app
logs) — replaces having to piece together what happened from uvicorn's
own access log, which doesn't know about request ids, auth, or which
user made the call.

Also stamps an `X-Request-ID` response header (generating one if the
client didn't send one), and puts it on `request.state.request_id` so
middleware/errors.py can include the same id in an error response body —
one id a person can search logs for, end to end.
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
