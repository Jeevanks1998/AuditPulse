"""
consent/cookies.py

Thin bridge between the standalone cookies/ package (detector,
categories, expiry, validator, storage — none of which know anything
about consent banners) and the rest of consent/: runs
cookies.run_cookie_checks and additionally cross-references each
cookie's category against consent/behavior.py's verdict to flag the
specific case that matters most for compliance — a non-essential
cookie that was set before the visitor consented at all.

Kept separate from cookies/storage.py on purpose: storage.py's
build_cookie_summary has no concept of "consent", so it stays reusable
outside this audit module; the consent-timing cross-reference belongs
here instead.
"""

from __future__ import annotations

from typing import List, Optional

from crawler.parser import ParsedPage

from cookies.categories import ESSENTIAL, categorize_cookie
from cookies.detector import Cookie
from cookies.storage import CookieAuditResult, run_cookie_checks

MODULE = "consent"
CATEGORY = "cookies"


def analyze_cookies(
    cookies: List[Cookie],
    page: Optional[ParsedPage] = None,
    first_party_hostname: Optional[str] = None,
    blocks_scripts_pre_consent: Optional[bool] = None,
) -> CookieAuditResult:
    """
    Runs the full cookies/ package pipeline, then — when a pre-consent
    verdict is available from consent.behavior.evaluate_behavior — adds
    findings for non-essential cookies observed on a page that doesn't
    block pre-consent scripts (the concrete evidence of the
    "banner is decorative" problem consent/behavior.py's verdict describes).
    """
    result = run_cookie_checks(cookies, page=page, first_party_hostname=first_party_hostname)

    if blocks_scripts_pre_consent is False:
        result.findings += check_pre_consent_cookies(cookies)

    return result


def check_pre_consent_cookies(cookies: List[Cookie]) -> List[dict]:
    """
    Flags non-essential cookies seen in the *initial HTTP response*
    (Set-Cookie headers from a single fetch) on a page whose scripts
    aren't confirmed to be held back pre-consent.

    Scope, stated plainly: this is detection + classification of what the
    server sent, not a before/after-consent timing measurement. It can't
    see cookies set later by JavaScript (most analytics/advertising ones)
    and says nothing about consent state. The authoritative "were
    non-essential cookies present before consent?" verdict is
    consent.runtime's before-consent snapshot, which
    consent_score._cookies_before_consent_check uses; this finding is
    the response-header complement to it.
    """
    non_essential = [c for c in cookies if categorize_cookie(c.name, c.domain) != ESSENTIAL]
    if not non_essential:
        return []

    names = ", ".join(sorted({c.name for c in non_essential})[:5])
    return [{
        "module": MODULE,
        "category": CATEGORY,
        "severity": "critical",
        "title": "Non-essential cookies set in the initial HTTP response",
        "description": f"{len(non_essential)} non-essential cookie(s) ({names}) were set by the server "
                        "in the page's initial response, on a site where scripts aren't confirmed to be "
                        "held back until consent. (Server-set cookies only — cookies set later by "
                        "JavaScript aren't visible to this check.)",
        "recommendation": "Confirm these cookies are only set after the visitor consents to "
                           "the relevant category, not unconditionally on page load.",
    }]
