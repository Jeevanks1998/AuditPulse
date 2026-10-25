"""
Turns every error into the {success, error} JSON the frontend expects,
including plain HTTPException(detail=...) from routes.
"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from fastapi.encoders import jsonable_encoder

from config.logging import logger


def _request_id(request: Request) -> str | None:
    # Set by middleware/logging.py; may be missing if an earlier layer failed.
    return getattr(request.state, "request_id", None)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning(f"Validation error on {request.url.path}: {exc.errors()}")
        # Drop "ctx" (it can hold an exception object, which can't be turned into JSON).
        details = [
            {k: v for k, v in err.items() if k != "ctx"} | (
                {"ctx": {ck: str(cv) for ck, cv in err["ctx"].items()}} if isinstance(err.get("ctx"), dict) else {}
            )
            for err in exc.errors()
        ]
        # Show the actual reason, e.g. "Please provide a valid website URL."
        first = details[0].get("msg", "") if details else ""
        message = first.removeprefix("Value error, ") if first else "Validation failed"
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder({
                "success": False,
                "error": message or "Validation failed",
                "details": details,
                "request_id": _request_id(request),
            }),
        )

    @app.exception_handler(HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        # Expected 4xx errors: just wrap them in the frontend's format.
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
