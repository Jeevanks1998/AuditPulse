"""
consent/cookies.py

Thin bridge between the standalone cookies/ package (detector,
categories, expiry, validator, storage — none of which know anything
about consent banners) and the rest of consent/.

Two separate evidence sources are kept apart on purpose:

  * static  — Set-Cookie headers from the single HTTP fetch of the page
              (`analyze_cookies` / `check_pre_consent_cookies`). Sees only
              server-set cookies; says nothing about timing.
  * runtime — the browser cookie jar captured by consent.runtime before
              any consent action (`bucket_cookies` is shared by both so
              they classify identically).

Classification rules that matter for consent verdicts:

  * analytics / marketing        -> consent required; present before
                                    consent = real evidence of a failure
  * consent_management           -> the CMP storing the visitor's choice
                                    (OptanonConsent…). Never a failure.
  * essential (session, CSRF/XSRF,
    load-balancing, bot protection) -> security/essential evidence. Never
                                    a failure.
  * functional                   -> reported, not judged
  * unknown                      -> stays UNKNOWN, reported as "needs
                                    review", never auto-promoted to
                                    non-essential.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from crawler.parser import ParsedPage

from cookies.categories import (
    CONSENT_MANAGEMENT,
    ESSENTIAL,
    FUNCTIONAL,
    classify_cookie,
    display_name,
    purpose_display_name,
    requires_consent,
)
from cookies.detector import Cookie
from cookies.storage import CookieAuditResult, run_cookie_checks

MODULE = "consent"
CATEGORY = "cookies"

_MAX_NAMES = 5


@dataclass
class CookieEvidenceItem:
    name: str
    domain: str
    category: str
    purpose: str
    vendor: Optional[str] = None

    def describe(self) -> str:
        bits = [display_name(self.category)]
        if self.purpose and self.purpose != "unknown":
            bits.append(purpose_display_name(self.purpose))
        if self.vendor:
            bits.append(self.vendor)
        dom = f" ({self.domain})" if self.domain else ""
        return f"{self.name}{dom} — {' · '.join(bits)}"


@dataclass
class CookieBuckets:
    """One set of cookies, split by what each one means for consent."""
    consent_required: List[CookieEvidenceItem] = field(default_factory=list)   # analytics + marketing
    consent_management: List[CookieEvidenceItem] = field(default_factory=list)
    essential: List[CookieEvidenceItem] = field(default_factory=list)          # session/security/LB/bot
    functional: List[CookieEvidenceItem] = field(default_factory=list)
    unknown: List[CookieEvidenceItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (len(self.consent_required) + len(self.consent_management) + len(self.essential)
                + len(self.functional) + len(self.unknown))

    def counts(self) -> Dict[str, int]:
        return {
            "consent_required": len(self.consent_required),
            "consent_management": len(self.consent_management),
            "essential": len(self.essential),
            "functional": len(self.functional),
            "unknown": len(self.unknown),
        }


def bucket_cookies(cookies: Iterable) -> CookieBuckets:
    """
    Accepts anything with `.name` and `.domain` (cookies.detector.Cookie,
    consent.runtime.CookieSnapshot) or dicts with those keys.
    """
    buckets = CookieBuckets()
    for c in cookies:
        name = c.get("name") if isinstance(c, dict) else getattr(c, "name", "")
        domain = (c.get("domain") if isinstance(c, dict) else getattr(c, "domain", "")) or ""
        cls = classify_cookie(name, domain)
        item = CookieEvidenceItem(name=name, domain=domain, category=cls.category,
                                  purpose=cls.purpose, vendor=cls.vendor)
        if requires_consent(cls.category):
            buckets.consent_required.append(item)
        elif cls.category == CONSENT_MANAGEMENT:
            buckets.consent_management.append(item)
        elif cls.category == ESSENTIAL:
            buckets.essential.append(item)
        elif cls.category == FUNCTIONAL:
            buckets.functional.append(item)
        else:
            buckets.unknown.append(item)
    return buckets


def analyze_cookies(
    cookies: List[Cookie],
    page: Optional[ParsedPage] = None,
    first_party_hostname: Optional[str] = None,
    blocks_scripts_pre_consent: Optional[bool] = None,
) -> CookieAuditResult:
    """
    Runs the full cookies/ package pipeline, then — when a pre-consent
    verdict is available from consent.behavior.evaluate_behavior — adds
    findings for consent-required cookies observed in the initial
    response on a page that doesn't block pre-consent scripts.
    """
    result = run_cookie_checks(cookies, page=page, first_party_hostname=first_party_hostname)

    if blocks_scripts_pre_consent is False:
        result.findings += check_pre_consent_cookies(cookies)

    return result


def check_pre_consent_cookies(cookies: List[Cookie]) -> List[dict]:
    """
    Flags analytics/marketing cookies seen in the *initial HTTP response*
    (Set-Cookie headers) on a page whose scripts aren't confirmed to be
    held back pre-consent.

    Consent-management cookies (OptanonConsent…) and essential
    session/security cookies (XSRF-TOKEN, session, CSRF…) are never
    flagged. Unknown cookies produce a separate low-severity "needs
    review" note rather than a consent failure.
    """
    buckets = bucket_cookies(cookies)
    findings: List[dict] = []

    if buckets.consent_required:
        names = ", ".join(sorted({c.name for c in buckets.consent_required})[:_MAX_NAMES])
        findings.append({
            "module": MODULE,
            "category": CATEGORY,
            "severity": "critical",
            "title": "Analytics/marketing cookies set in the initial HTTP response",
            "description": f"{len(buckets.consent_required)} analytics/marketing cookie(s) ({names}) were set "
                            "by the server in the page's initial response, on a site where scripts aren't "
                            "confirmed to be held back until consent. (Server-set cookies only — cookies "
                            "set later by JavaScript aren't visible to this check.)",
            "recommendation": "Confirm these cookies are only set after the visitor consents to "
                               "the relevant category, not unconditionally on page load.",
        })

    if buckets.unknown:
        names = ", ".join(sorted({c.name for c in buckets.unknown})[:_MAX_NAMES])
        findings.append({
            "module": MODULE,
            "category": CATEGORY,
            "severity": "info",
            "title": "Unclassified cookies in the initial HTTP response",
            "description": f"{len(buckets.unknown)} cookie(s) ({names}) could not be matched to a known "
                            "purpose. They are reported as UNKNOWN and are not treated as a consent "
                            "failure.",
            "recommendation": "Review these cookies' purpose and document them in the cookie policy.",
        })

    return findings
