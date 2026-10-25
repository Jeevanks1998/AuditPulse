"""
1. detect_browser_storage: finds localStorage / sessionStorage / IndexedDB use
   in the page's scripts (consent rules cover these too, not just cookies).
2. build_cookie_summary: the cookie list and third-party trackers saved
   with the consent results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from crawler.parser import ParsedPage

from cookies.categories import categorize_cookie, display_name, requires_consent
from cookies.detector import Cookie, is_third_party
from cookies.expiry import EXCESSIVE, classify_expiry, describe_lifetime

MODULE = "consent"
CATEGORY = "cookies"

_LOCAL_STORAGE_RE = re.compile(r"\blocalStorage\s*\.\s*(setItem|getItem)\s*\(\s*['\"]([^'\"]+)['\"]")
_SESSION_STORAGE_RE = re.compile(r"\bsessionStorage\s*\.\s*(setItem|getItem)\s*\(\s*['\"]([^'\"]+)['\"]")
_INDEXED_DB_RE = re.compile(r"\bindexedDB\s*\.\s*open\s*\(")

_MAX_SAMPLE_KEYS = 10


@dataclass
class BrowserStorageDetection:
    local_storage_used: bool = False
    session_storage_used: bool = False
    indexed_db_used: bool = False
    local_storage_keys: List[str] = field(default_factory=list)
    session_storage_keys: List[str] = field(default_factory=list)


def detect_browser_storage(page: ParsedPage) -> BrowserStorageDetection:
    """Looks for localStorage / sessionStorage / IndexedDB calls in scripts."""
    result = BrowserStorageDetection()
    local_keys: List[str] = []
    session_keys: List[str] = []

    for tag in page.soup.find_all("script"):
        body = tag.string or tag.get_text() or ""
        if not body:
            continue

        for match in _LOCAL_STORAGE_RE.finditer(body):
            result.local_storage_used = True
            local_keys.append(match.group(2))
        for match in _SESSION_STORAGE_RE.finditer(body):
            result.session_storage_used = True
            session_keys.append(match.group(2))
        if _INDEXED_DB_RE.search(body):
            result.indexed_db_used = True

    result.local_storage_keys = list(dict.fromkeys(local_keys))[:_MAX_SAMPLE_KEYS]
    result.session_storage_keys = list(dict.fromkeys(session_keys))[:_MAX_SAMPLE_KEYS]
    return result


def check_browser_storage(page: ParsedPage) -> List[dict]:
    """One info finding when browser storage is used (not a problem by itself)."""
    detection = detect_browser_storage(page)
    if not (detection.local_storage_used or detection.session_storage_used or detection.indexed_db_used):
        return []

    mechanisms = []
    if detection.local_storage_used:
        mechanisms.append("localStorage")
    if detection.session_storage_used:
        mechanisms.append("sessionStorage")
    if detection.indexed_db_used:
        mechanisms.append("IndexedDB")

    return [{
        "module": MODULE,
        "category": CATEGORY,
        "severity": "info",
        "title": "Client-side storage in use alongside cookies",
        "description": f"{page.url} uses {', '.join(mechanisms)} — under most consent "
                        "frameworks this counts the same as a cookie and should be covered "
                        "by the same disclosure/consent flow.",
        "recommendation": "Confirm the privacy policy and consent banner's category "
                           "descriptions cover client-side storage, not just cookies.",
    }]


def check_retention(cookies: List[Cookie]) -> List[dict]:
    """Flags cookies that live too long for their category."""
    findings: List[dict] = []
    for cookie in cookies:
        category = categorize_cookie(cookie.name, cookie.domain)
        classification = classify_expiry(cookie.max_age_seconds, category)
        if not classification.exceeds_category_guidance:
            continue
        severity = "critical" if classification.lifetime_bucket == EXCESSIVE else "warning"
        findings.append({
            "module": MODULE,
            "category": CATEGORY,
            "severity": severity,
            "title": f"Cookie '{cookie.name}' retained longer than typical guidance",
            "description": f"'{cookie.name}' ({display_name(category)}) {describe_lifetime(classification)}, "
                            f"which exceeds common retention guidance for its category.",
            "recommendation": "Shorten the cookie's lifetime to what's necessary for its "
                               "stated purpose, or document the justification in the privacy policy.",
            "cookie": cookie.name,
        })
    return findings


@dataclass
class CookieSummary:
    """Cookie fields saved with the consent results."""
    cookies_detected: List[dict] = field(default_factory=list)      # [{name, category, domain, expires}]
    third_party_trackers: List[str] = field(default_factory=list)   # domains, no duplicates
    counts_by_category: Dict[str, int] = field(default_factory=dict)


def build_cookie_summary(cookies: List[Cookie], first_party_hostname: Optional[str] = None) -> CookieSummary:
    detected: List[dict] = []
    trackers: List[str] = []
    counts: Dict[str, int] = {}

    for cookie in cookies:
        category = categorize_cookie(cookie.name, cookie.domain)
        counts[category] = counts.get(category, 0) + 1
        classification = classify_expiry(cookie.max_age_seconds, category)

        detected.append({
            "name": cookie.name,
            "category": category,
            "domain": cookie.domain,
            "expires": classification.lifetime_days if classification.lifetime_days is not None else "session",
        })

        # Only analytics/marketing cookies count as trackers.
        if is_third_party(cookie, first_party_hostname) and cookie.domain and requires_consent(category):
            trackers.append(cookie.domain)

    return CookieSummary(
        cookies_detected=detected,
        third_party_trackers=list(dict.fromkeys(trackers)),
        counts_by_category=counts,
    )


@dataclass
class CookieAuditResult:
    findings: List[dict]
    summary: CookieSummary
    storage: BrowserStorageDetection


def run_cookie_checks(
    cookies: List[Cookie],
    page: Optional[ParsedPage] = None,
    first_party_hostname: Optional[str] = None,
) -> CookieAuditResult:
    """Runs all cookie checks and builds the summary. `page` is optional."""
    from cookies.validator import validate_cookies  # local import avoids a cycle

    findings = validate_cookies(cookies, first_party_hostname) + check_retention(cookies)
    storage = BrowserStorageDetection()
    if page is not None:
        storage = detect_browser_storage(page)
        findings += check_browser_storage(page)

    summary = build_cookie_summary(cookies, first_party_hostname)
    return CookieAuditResult(findings=findings, summary=summary, storage=storage)
