"""
middleware/errors.py

Exception handlers -> the `{ success, error }` JSON shape
assets/js/api.js's callers already expect (see main.py's original
validation/unhandled handlers, moved here unchanged) — plus the one gap
those two didn't cover: a plain `HTTPException` (`raise HTTPException(...,
detail="...")`, which is how almost every route in api/ reports a 404/
401/409/etc.) fell through to FastAPI's default `{"detail": "..."}`
body instead of the same shape. That's fixed here without touching any
of the ~40 call sites that raise HTTPException across api/ and
services/ — they keep using `detail=`, this handler just re-shapes the
response.
"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config.logging import logger


def _request_id(request: Request) -> str | None:
    # Set by middleware/logging.py; may be absent if that middleware
    # hasn't run yet (e.g. an error raised by another middleware ahead
    # of it in the stack), so this stays optional rather than required.
    return getattr(request.state, "request_id", None)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning(f"Validation error on {request.url.path}: {exc.errors()}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "error": "Validation failed",
                "details": exc.errors(),
                "request_id": _request_id(request),
            },
        )

    @app.exception_handler(HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # 4xx from an expected/handled condition (not found, unauthenticated,
        # conflict, ...) — routes already chose the right status/detail, this
        # only wraps it in the shape the frontend understands.
        if exc.status_code >= 500:
            logger.error(f"{request.method} {request.url.path} -> {exc.status_code}: {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": exc.detail,
                "request_id": _request_id(request),
            },
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled error on {request.url.path}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": "Internal server error",
                "request_id": _request_id(request),
            },
        )
