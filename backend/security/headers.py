"""
security/headers.py

Checks the general-purpose security response headers — everything
except Strict-Transport-Security and Content-Security-Policy, which
are involved enough (directive parsing, max-age math) to get their own
modules (hsts.py, csp.py). Takes a plain header dict rather than an
httpx.Headers/response object so it's easy to unit test and to feed
from any fetch path (security/https.py's live GET today; a cached
response tomorrow).

Header names are matched case-insensitively by lowercasing every key
up front, since HTTP header names are case-insensitive but Python
dicts aren't.
"""

from __future__ import annotations

from typing import List, Mapping, Optional

MODULE = "security"
CATEGORY = "headers"


def check_security_headers(headers: Mapping[str, str], url: str) -> List[dict]:
    """Findings for missing or misconfigured general security headers."""
    if not headers:
        return []

    lower = {k.lower(): v for k, v in headers.items()}
    findings: List[dict] = []

    findings += _check_content_type_options(lower, url)
    findings += _check_frame_protection(lower, url)
    findings += _check_referrer_policy(lower, url)
    findings += _check_permissions_policy(lower, url)
    findings += _check_cross_origin_isolation(lower, url)
    findings += _check_info_disclosure(lower, url)

    return findings


def _check_content_type_options(headers: dict, url: str) -> List[dict]:
    value = headers.get("x-content-type-options", "")
    if value.strip().lower() == "nosniff":
        return []
    return [_finding(
        "warning",
        "Missing X-Content-Type-Options header",
        f"{url} does not send `X-Content-Type-Options: nosniff`. Without it, some browsers "
        "will try to guess ('sniff') a resource's MIME type from its content rather than "
        "trusting the declared Content-Type, which can let a file uploaded as an image be "
        "executed as script in certain scenarios.",
        recommendation="Add the response header `X-Content-Type-Options: nosniff` to every "
                        "response.",
    )]


def _check_frame_protection(headers: dict, url: str) -> List[dict]:
    """X-Frame-Options is legacy but still widely checked; CSP frame-ancestors supersedes it."""
    has_xfo = "x-frame-options" in headers
    csp = headers.get("content-security-policy", "")
    has_frame_ancestors = "frame-ancestors" in csp.lower()

    if has_xfo or has_frame_ancestors:
        if has_xfo and headers["x-frame-options"].strip().upper() not in ("DENY", "SAMEORIGIN"):
            return [_finding(
                "info",
                "Unrecognized X-Frame-Options value",
                f"{url} sends `X-Frame-Options: {headers['x-frame-options']}`, which isn't "
                "one of the two values browsers actually support (DENY, SAMEORIGIN) and will "
                "be ignored.",
                recommendation="Use `X-Frame-Options: SAMEORIGIN` (or DENY if the site never "
                                "needs to be framed), or rely on CSP's frame-ancestors instead.",
            )]
        return []

    return [_finding(
        "warning",
        "Missing clickjacking protection",
        f"{url} sets neither `X-Frame-Options` nor a CSP `frame-ancestors` directive. Without "
        "either, the page can be embedded in an invisible or disguised <iframe> on another "
        "site to trick users into clicking something they didn't intend to (clickjacking).",
        recommendation="Add `Content-Security-Policy: frame-ancestors 'self'` (preferred), or "
                        "`X-Frame-Options: SAMEORIGIN` for broader legacy-browser support.",
    )]


def _check_referrer_policy(headers: dict, url: str) -> List[dict]:
    value = headers.get("referrer-policy", "").strip().lower()
    if not value:
        return [_finding(
            "info",
            "Missing Referrer-Policy header",
            f"{url} does not send a `Referrer-Policy` header. Browsers then fall back to "
            "sending the full referring URL — including any query-string data — to every "
            "link that's followed and every third-party resource that's loaded.",
            recommendation="Add `Referrer-Policy: strict-origin-when-cross-origin` (a safe, "
                            "widely-supported default) or a stricter policy if the site never "
                            "needs referrer data to leave its own origin.",
        )]
    if value in ("unsafe-url",):
        return [_finding(
            "warning",
            "Overly permissive Referrer-Policy",
            f"{url} sets `Referrer-Policy: unsafe-url`, which sends the full URL — including "
            "path and query string — as the referrer on every navigation and subresource "
            "request, even from HTTPS to HTTP.",
            recommendation="Switch to `strict-origin-when-cross-origin` or `same-origin` "
                            "unless a specific integration genuinely needs the full URL.",
        )]
    return []


def _check_permissions_policy(headers: dict, url: str) -> List[dict]:
    if "permissions-policy" in headers or "feature-policy" in headers:
        return []
    return [_finding(
        "info",
        "Missing Permissions-Policy header",
        f"{url} does not send a `Permissions-Policy` header, so every powerful browser API "
        "(camera, microphone, geolocation, USB, etc.) stays available to any script running "
        "on the page — including third-party scripts — with no opt-out declared.",
        recommendation="Add a `Permissions-Policy` header that explicitly disables APIs the "
                        "site doesn't use, e.g. `Permissions-Policy: camera=(), "
                        "microphone=(), geolocation=()`.",
    )]


def _check_cross_origin_isolation(headers: dict, url: str) -> List[dict]:
    findings: List[dict] = []
    if "cross-origin-opener-policy" not in headers:
        findings.append(_finding(
            "info",
            "Missing Cross-Origin-Opener-Policy header",
            f"{url} does not send `Cross-Origin-Opener-Policy`, leaving the page's window "
            "reachable from cross-origin popups it opens (or that open it), which can enable "
            "cross-window attacks like tabnabbing-style reference leaks.",
            recommendation="Add `Cross-Origin-Opener-Policy: same-origin` unless the site "
                            "specifically relies on cross-origin window references.",
        ))
    return findings


_INFO_LEAK_HEADERS = ("server", "x-powered-by", "x-aspnet-version", "x-aspnetmvc-version")


def _check_info_disclosure(headers: dict, url: str) -> List[dict]:
    leaking = [h for h in _INFO_LEAK_HEADERS if headers.get(h)]
    if not leaking:
        return []
    details = ", ".join(f"{h}: {headers[h]}" for h in leaking)
    return [_finding(
        "info",
        "Server software/version disclosed in response headers",
        f"{url} exposes implementation details via response headers ({details}). This makes "
        "it easier for an attacker to look up known vulnerabilities for the exact software "
        "version in use.",
        recommendation="Suppress or generalize these headers at the server/proxy level (e.g. "
                        "`server_tokens off;` in nginx, removing X-Powered-By in most "
                        "frameworks).",
    )]


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
