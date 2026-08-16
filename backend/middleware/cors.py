"""
middleware/cors.py

CORS configuration, pulled out of main.py's inline
`app.add_middleware(CORSMiddleware, ...)` call so it lives next to the
rest of the request-handling layer. Behavior is unchanged from what
main.py had — same settings.CORS_ORIGINS source, same allow_methods /
allow_headers — plus two settings that were previously hardcoded
(credentials, preflight cache lifetime) now living in config.settings
alongside CORS_ORIGINS_RAW instead of as magic values here.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings


def add_cors_middleware(app: FastAPI) -> None:
    """The static frontend (assets/js/api.js) calls this API from a
    different origin during local development (see settings.CORS_ORIGINS
    / the CORS_ORIGINS_RAW env var), so every route needs CORS headers —
    added last in middleware/__init__.py's setup_middleware so this is
    the outermost layer and CORS headers reach even 401/429/500
    responses from the other middleware.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=["*"],
        # Lets browsers read the request-id header middleware/logging.py
        # stamps onto every response, useful for client-side error reports.
        expose_headers=["X-Request-ID"],
        max_age=settings.CORS_MAX_AGE_SECONDS,
    )
