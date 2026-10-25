"""
Security headers on every API response: no MIME sniffing, no framing, no referrer, HTTPS only, strict CSP.
"""

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Resource-Policy": "cross-origin",   # screenshots are loaded by the frontend on Vercel
}
_JSON_CSP = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for k, v in _HEADERS.items():
            response.headers.setdefault(k, v)
        if response.headers.get("content-type", "").startswith("application/json"):
            response.headers.setdefault("Content-Security-Policy", _JSON_CSP)
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


def add_security_headers_middleware(app: FastAPI) -> None:
    app.add_middleware(SecurityHeadersMiddleware)
