"""
cookies/storage.py

Two jobs that both boil down to "what does this site store client-side,
and is it declared to the visitor":

1. `detect_browser_storage` — static regex scan of a page's <script>
   tags (same technique as analytics/ga4.py reading ParsedPage.soup)
   for localStorage/sessionStorage/IndexedDB usage. Cookies aren't the
   only client-side storage a consent banner is supposed to cover —
   GDPR's definition of "cookies" for consent purposes (ePrivacy
   Directive Art. 5(3)) already extends to any client-side storage
   mechanism, so a site that only audits actual Set-Cookie headers
   while ignoring a localStorage-based tracker misses real exposure.

2. `build_cookie_summary` — folds a List[Cookie] (cookies.detector)
   through categorization + expiry into the flat shape
   models.consent.Consent actually persists: `cookies_detected`
   ([{name, category, domain, expires}]) and `third_party_trackers`
   ([vendor/domain names]). Mirrors
   analytics.analytics_score.build_analytics_summary's role for the
   Analytics model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from crawler.parser import ParsedPage

from cookies.categories import UNKNOWN, categorize_cookie, display_name
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
    """Scans inline/attached <script> text for localStorage/sessionStorage/IndexedDB calls."""
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
    """
    A single info-level finding when client-side storage is used, since
    presence alone isn't a defect — only that it's covered by the
    banner's disclosure (consent.preferences checks the disclosure
    itself). Kept separate from the cookie findings so a site with zero
    cookies but heavy localStorage tracking still surfaces something.
    """
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
    """Flags cookies whose lifetime exceeds what's reasonable for their category."""
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
    """Field-for-field match with the list-valued columns on models.consent.Consent."""
    cookies_detected: List[dict] = field(default_factory=list)      # [{name, category, domain, expires}]
    third_party_trackers: List[str] = field(default_factory=list)   # domains, de-duped
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

        if is_third_party(cookie, first_party_hostname) and cookie.domain and category != UNKNOWN:
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
    """
    One-call entry point combining validator + retention + browser
    storage findings with the persistence-ready summary. `page` is
    optional so this still works from a context that only has raw
    Set-Cookie headers and no parsed page (e.g. a unit test).
    """
    from cookies.validator import validate_cookies  # local import avoids a cycle with detector-only callers

    findings = validate_cookies(cookies, first_party_hostname) + check_retention(cookies)
    storage = BrowserStorageDetection()
    if page is not None:
        storage = detect_browser_storage(page)
        findings += check_browser_storage(page)

    summary = build_cookie_summary(cookies, first_party_hostname)
    return CookieAuditResult(findings=findings, summary=summary, storage=storage)
