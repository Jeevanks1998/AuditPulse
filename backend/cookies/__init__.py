"""
cookies/

Standalone cookie-analysis package used by consent/ (see
consent/cookies.py) to back the "consent" audit module's cookie table
(models.consent.Consent.cookies_detected /
.third_party_trackers) with real data instead of
services.audit_service._write_consent_result's hardcoded placeholder
row.

    detector    — parses raw Set-Cookie header strings into Cookie
                  objects (name, domain, path, Secure/HttpOnly/
                  SameSite, resolved lifetime)
    categories  — classifies a cookie name/domain into essential /
                  functional / analytics / marketing / unknown
    expiry      — classifies a cookie's lifetime and flags retention
                  that's excessive for its category
    validator   — Secure/HttpOnly/SameSite attribute checks -> findings
    storage     — ties the above together: browser storage
                  (localStorage/sessionStorage/IndexedDB) detection,
                  retention findings, and build_cookie_summary(), the
                  models.consent.Consent-ready summary

Every finding here uses module="consent", category="cookies" — the
same {module, category, severity, title, description, recommendation}
shape every other check package returns (see analytics/__init__.py),
so nothing downstream (Issue sync, report.html) needs to change to
consume them.

Usage — from something that already has raw Set-Cookie header values
for a fetched page (e.g. an httpx.Response) and, optionally, that
page's ParsedPage:

    from cookies import parse_set_cookie_headers, run_cookie_checks

    cookies = parse_set_cookie_headers(response.headers.get_list("set-cookie"), source_url=url)
    result = run_cookie_checks(cookies, page=parsed_page, first_party_hostname=hostname)
    # result.findings -> list[dict], result.summary -> CookieSummary
"""

from __future__ import annotations

from cookies.categories import (
    ANALYTICS,
    CATEGORIES,
    ESSENTIAL,
    FUNCTIONAL,
    MARKETING,
    UNKNOWN,
    categorize_cookie,
    display_name,
)
from cookies.detector import Cookie, is_third_party, merge_cookie_lists, parse_set_cookie_headers
from cookies.expiry import ExpiryClassification, classify_expiry, describe_lifetime
from cookies.storage import (
    BrowserStorageDetection,
    CookieAuditResult,
    CookieSummary,
    build_cookie_summary,
    check_browser_storage,
    check_retention,
    detect_browser_storage,
    run_cookie_checks,
)
from cookies.validator import validate_cookie, validate_cookies

__all__ = [
    "Cookie", "parse_set_cookie_headers", "merge_cookie_lists", "is_third_party",
    "categorize_cookie", "display_name", "CATEGORIES",
    "ESSENTIAL", "FUNCTIONAL", "ANALYTICS", "MARKETING", "UNKNOWN",
    "classify_expiry", "describe_lifetime", "ExpiryClassification",
    "validate_cookie", "validate_cookies",
    "detect_browser_storage", "check_browser_storage", "check_retention",
    "build_cookie_summary", "run_cookie_checks",
    "BrowserStorageDetection", "CookieSummary", "CookieAuditResult",
]
