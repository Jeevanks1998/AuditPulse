"""
CORS set-up (origins from settings.CORS_ORIGINS).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings


def add_cors_middleware(app: FastAPI) -> None:
    """The frontend runs on another domain, so every route needs CORS headers. Added as the outermost layer."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=["*"],
        # Let browsers read the X-Request-ID header.
        expose_headers=["X-Request-ID"],
        max_age=settings.CORS_MAX_AGE_SECONDS,
    )
