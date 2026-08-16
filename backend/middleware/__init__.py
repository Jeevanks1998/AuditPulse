"""
middleware/

Cross-cutting request handling, pulled out of main.py so each concern is
independently readable/testable instead of living inline in the app
factory. Mirrors config/config.py's role for the config/ package: a thin
aggregator so main.py can do

    from middleware import setup_middleware
    setup_middleware(app)

instead of importing and wiring five modules by hand.

  cors.py       - allowed-origin / credentials / preflight config
  logging.py    - one structured log line per request (method, path,
                   status, latency, user, request id)
  auth.py       - resolves the caller (JWT bearer or X-API-Key) onto
                   request.state ahead of routing, so logging/rate_limit
                   can key off a user instead of just an IP. Does not
                   replace api/auth.py's `get_current_user` dependency —
                   routes still enforce auth themselves; this only makes
                   "who is this" available earlier and to non-route code.
  rate_limit.py - per-IP/per-user request throttling, Redis-backed with
                  an in-memory fallback
  errors.py     - exception handlers -> the {success, error} JSON shape
                  the frontend's Notifications.error(...) calls expect

Order matters here: Starlette's middleware stack runs in the *reverse*
of the order each layer is added (the last one added wraps everything
else), so setup_middleware adds CORS last, making it the outermost
layer — every response, including error responses and rate-limit 429s,
still carries the right CORS headers, and preflight OPTIONS requests get
answered before hitting auth/rate-limit/logging at all.
"""

from fastapi import FastAPI

from middleware.auth import add_auth_context_middleware
from middleware.cors import add_cors_middleware
from middleware.errors import register_error_handlers
from middleware.logging import add_logging_middleware
from middleware.rate_limit import add_rate_limit_middleware


def setup_middleware(app: FastAPI) -> None:
    """Wires every middleware layer + exception handler onto `app`. Call
    once from main.py, after the FastAPI() instance is created and
    before app.include_router(...).
    """
    register_error_handlers(app)

    # Innermost -> outermost (see module docstring for why this order).
    add_auth_context_middleware(app)
    add_logging_middleware(app)
    add_rate_limit_middleware(app)
    add_cors_middleware(app)


__all__ = ["setup_middleware"]
