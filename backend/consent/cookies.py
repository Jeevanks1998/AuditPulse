"""
Connects the cookies/ package to the consent checks. Two sources, kept apart:
  static  - Set-Cookie headers from one fetch (server cookies only, no timing)
  runtime - the browser's cookies before any consent click

Only analytics / marketing cookies before consent are failures. Consent-tool
cookies, essential cookies (session, CSRF, load balancing, bot protection),
functional and unknown cookies never are; unknown ones are "needs review".
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
    """Cookies grouped by what they mean for consent."""
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
    """Accepts cookie objects or dicts with `name` and `domain`."""
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
    """Runs the cookies/ checks, plus findings for consent-required cookies when tracking isn't held back."""
    result = run_cookie_checks(cookies, page=page, first_party_hostname=first_party_hostname)

    if blocks_scripts_pre_consent is False:
        result.findings += check_pre_consent_cookies(cookies)

    return result


def check_pre_consent_cookies(cookies: List[Cookie]) -> List[dict]:
    """Flags analytics/marketing cookies in the first response when scripts aren't
    confirmed to wait for consent. Consent-tool and essential cookies are never
    flagged; unknown ones get a low "needs review" note.
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
