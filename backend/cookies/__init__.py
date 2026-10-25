"""
Cookie analysis used by the consent checks:
  detector   - reads Set-Cookie headers into Cookie objects
  categories - essential / functional / analytics / marketing / unknown
  expiry     - lifetime, and whether it's too long for the category
  validator  - Secure / HttpOnly / SameSite checks
  storage    - browser storage detection and the saved cookie summary
Findings use module="consent", category="cookies".
"""

from __future__ import annotations

from cookies.categories import (
    ANALYTICS,
    CATEGORIES,
    CONSENT_MANAGEMENT,
    CONSENT_REQUIRED_CATEGORIES,
    CookieClassification,
    ESSENTIAL,
    FUNCTIONAL,
    MARKETING,
    UNKNOWN,
    categorize_cookie,
    classify_cookie,
    display_name,
    requires_consent,
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
    "categorize_cookie", "classify_cookie", "requires_consent", "display_name", "CATEGORIES",
    "CookieClassification", "CONSENT_REQUIRED_CATEGORIES",
    "ESSENTIAL", "FUNCTIONAL", "ANALYTICS", "MARKETING", "CONSENT_MANAGEMENT", "UNKNOWN",
    "classify_expiry", "describe_lifetime", "ExpiryClassification",
    "validate_cookie", "validate_cookies",
    "detect_browser_storage", "check_browser_storage", "check_retention",
    "build_cookie_summary", "run_cookie_checks",
    "BrowserStorageDetection", "CookieSummary", "CookieAuditResult",
]
