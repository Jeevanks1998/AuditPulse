"""
cookies/validator.py

Validates the security-relevant attributes of already-parsed cookies
(cookies.detector.Cookie) — Secure, HttpOnly, SameSite — and turns
violations into findings in the same {module, category, severity,
title, description, recommendation} shape every other check package
in this codebase returns (see analytics/ga4.py, seo/meta.py).

`module` is "consent" here, not "cookies" — cookies/ has no entry of
its own in config.constants.AUDIT_MODULES; it's a supporting package
for the "consent" checkbox on audit.html, same relationship
crawler/parser.py has to seo/ and accessibility/. `category` is
"cookies" so consent/consent_score.py can weight it independently of
banner/consent-mode/network findings.
"""

from __future__ import annotations

from typing import List, Optional

from cookies.detector import Cookie, is_third_party

MODULE = "consent"
CATEGORY = "cookies"

VALID_SAMESITE_VALUES = {"Strict", "Lax", "None"}


def validate_cookie(cookie: Cookie, first_party_hostname: Optional[str] = None) -> List[dict]:
    """Findings for one cookie's security attributes. A fully-compliant cookie produces none."""
    findings: List[dict] = []
    third_party = is_third_party(cookie, first_party_hostname)

    if cookie.same_site and cookie.same_site not in VALID_SAMESITE_VALUES:
        findings.append(_finding(
            "warning",
            f"Cookie '{cookie.name}' has an invalid SameSite value",
            f"SameSite={cookie.same_site!r} isn't a recognized value (Strict/Lax/None); "
            "browsers will fall back to their default handling, which varies by vendor.",
            recommendation="Set SameSite to Strict, Lax, or None explicitly.",
            cookie=cookie.name,
        ))

    if cookie.same_site == "None" and not cookie.secure:
        findings.append(_finding(
            "critical",
            f"Cookie '{cookie.name}' uses SameSite=None without Secure",
            f"'{cookie.name}' is set with SameSite=None but no Secure attribute — modern "
            "browsers (Chrome, Firefox) reject this combination outright and drop the cookie.",
            recommendation="Add the Secure attribute whenever SameSite=None is used.",
            cookie=cookie.name,
        ))

    if third_party and not cookie.secure:
        findings.append(_finding(
            "warning",
            f"Third-party cookie '{cookie.name}' missing Secure",
            f"'{cookie.name}' is set by {cookie.domain} without the Secure attribute, so it "
            "can be sent over plain HTTP as well as HTTPS.",
            recommendation="Set the Secure attribute on all third-party cookies.",
            cookie=cookie.name,
        ))

    if _looks_like_session_identifier(cookie.name) and not cookie.http_only:
        findings.append(_finding(
            "critical",
            f"Session cookie '{cookie.name}' is missing HttpOnly",
            f"'{cookie.name}' looks like a session/auth cookie but has no HttpOnly attribute, "
            "so it's readable from JavaScript — a single XSS bug is enough to steal it.",
            recommendation="Set HttpOnly on all session/authentication cookies.",
            cookie=cookie.name,
        ))

    if third_party and (cookie.same_site is None):
        findings.append(_finding(
            "info",
            f"Third-party cookie '{cookie.name}' has no explicit SameSite",
            f"'{cookie.name}' from {cookie.domain} doesn't set SameSite explicitly; behavior "
            "then depends on the browser's default (Lax in most current browsers).",
            recommendation="Set SameSite explicitly rather than relying on browser defaults.",
            cookie=cookie.name,
        ))

    return findings


def validate_cookies(cookies: List[Cookie], first_party_hostname: Optional[str] = None) -> List[dict]:
    findings: List[dict] = []
    for cookie in cookies:
        findings += validate_cookie(cookie, first_party_hostname)
    return findings


def _looks_like_session_identifier(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("session", "sessid", "auth", "token", "login"))


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None,
             cookie: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
        "cookie": cookie,
    }
