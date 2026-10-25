"""
Request handling layers, set up by setup_middleware(app):
  cors.py       - allowed origins
  logging.py    - one log line per request
  auth.py       - works out who is calling (token or API key) for logging and
                  rate limits; routes still enforce auth themselves
  rate_limit.py - request limits (Redis, with in-memory fallback)
  errors.py     - errors as the {success, error} JSON the frontend expects

CORS is added last so it is the outermost layer: every response, even
errors and 429s, gets CORS headers.
"""

from fastapi import FastAPI

from middleware.auth import add_auth_context_middleware
from middleware.cors import add_cors_middleware
from middleware.errors import register_error_handlers
from middleware.logging import add_logging_middleware
from middleware.rate_limit import add_rate_limit_middleware


from middleware.security_headers import add_security_headers_middleware


def setup_middleware(app: FastAPI) -> None:
    """Adds every middleware and error handler. Call once in main.py."""
    register_error_handlers(app)

    # Innermost first, outermost last (see above).
    add_security_headers_middleware(app)
    add_auth_context_middleware(app)
    add_logging_middleware(app)
    add_rate_limit_middleware(app)
    add_cors_middleware(app)


__all__ = ["setup_middleware"]
