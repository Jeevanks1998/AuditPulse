"""
consent/buttons.py

Looks at every <button>/<a> in the page for consent-banner-style call
to actions and classifies each as accept / reject / manage-preferences,
then checks the classic "dark pattern" complaint regulators
(CNIL, ICO) have specifically called out: an "Accept All" button that's
one click away while "Reject All" is missing, buried in a sub-menu, or
requires more clicks than accepting does.

Static/markup-only, same as banner.py — this reads text + attributes,
it doesn't measure rendered click depth or visual prominence (that
would need consent/network.py's Playwright path).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from crawler.parser import ParsedPage

MODULE = "consent"
CATEGORY = "buttons"

# Exact-phrase allowlists first (normalized via _normalize below) so the
# specific wordings sites actually ship — "I Agree", "Only Necessary",
# "Your Privacy Choices", etc. — are recognized outright rather than
# relying on a single generic pattern to happen to cover them.
_ACCEPT_LABELS = {
    "accept",
    "accept all",
    "allow",
    "allow all",
    "agree",
    "i agree",
    "continue",
    "accept cookies",
    "allow all cookies",
}
_REJECT_LABELS = {
    "reject",
    "reject all",
    "decline",
    "decline all",
    "deny",
    "deny all",
    "continue without accepting",
    "only necessary",
    "necessary only",
}
_MANAGE_LABELS = {
    "manage preferences",
    "cookie settings",
    "privacy settings",
    "customize",
    "customise",
    "manage cookies",
    "cookie preferences",
    "your privacy choices",
}

# Fallback patterns catch close variations not in the exact lists above
# (e.g. "Accept All Cookies", "Reject Non-Essential", "Customize Settings")
# without needing every possible wording enumerated by hand.
_ACCEPT_RE = re.compile(
    r"^\s*(accept|allow|agree)\s*(all)?\s*(cookies|everything)?\s*$", re.IGNORECASE
)
_REJECT_RE = re.compile(
    r"^\s*(reject|decline|deny|disagree)\s*(all)?\s*(cookies|non[\s-]?essential)?\s*$"
    r"|^\s*(only\s+)?necessary(\s+only)?\s*$"
    r"|^\s*continue without accepting\s*$",
    re.IGNORECASE,
)
_MANAGE_RE = re.compile(
    r"^\s*(manage|customi[sz]e)\s*.*$"
    r"|^\s*(cookie|privacy)\s+(settings|preferences|choices)\s*$"
    r"|^\s*(your\s+)?privacy\s+(settings|choices)\s*$"
    r"|^\s*more options\s*$",
    re.IGNORECASE,
)


def _normalize(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().lower())


@dataclass
class ButtonsDetection:
    accept_found: bool = False
    reject_found: bool = False
    manage_found: bool = False
    accept_labels: List[str] = field(default_factory=list)
    reject_labels: List[str] = field(default_factory=list)
    manage_labels: List[str] = field(default_factory=list)

    @property
    def has_reject_parity(self) -> bool:
        """True when reject is offered at all — the bar this module checks, not visual weight."""
        return self.accept_found and self.reject_found


def detect_buttons(page: ParsedPage) -> ButtonsDetection:
    result = ButtonsDetection()
    candidates = page.soup.find_all(["button", "a", "input"])

    for tag in candidates:
        label = _label_of(tag)
        if not label:
            continue

        normalized = _normalize(label)

        # Reject is checked before accept: reject phrases like "Continue
        # Without Accepting" or "Necessary Only" can otherwise get pulled
        # into a looser accept pattern first.
        if normalized in _REJECT_LABELS or _REJECT_RE.match(label):
            result.reject_found = True
            result.reject_labels.append(label)
        elif normalized in _ACCEPT_LABELS or _ACCEPT_RE.match(label):
            result.accept_found = True
            result.accept_labels.append(label)
        elif normalized in _MANAGE_LABELS or _MANAGE_RE.match(label):
            result.manage_found = True
            result.manage_labels.append(label)

    return result


def check_buttons(page: ParsedPage, banner_detected: bool = True) -> List[dict]:
    """
    `banner_detected` lets the caller skip these findings entirely when
    consent.banner.detect_banner already found nothing — banner.py's
    own "no banner" finding is the more useful one in that case, and
    firing both would double-count the same underlying gap.
    """
    if not banner_detected:
        return []

    detection = detect_buttons(page)
    findings: List[dict] = []

    if detection.accept_found and not detection.reject_found:
        findings.append(_finding(
            "critical",
            "Accept-all button present with no equivalent reject option",
            f"{page.url}'s consent banner offers a one-click 'Accept' but no equally "
            "direct way to reject non-essential cookies — a pattern GDPR regulators "
            "(CNIL, ICO) have explicitly flaged as non-compliant.",
            recommendation="Offer 'Reject All' with the same prominence and click-depth as 'Accept All'.",
        ))
    elif not detection.accept_found and not detection.reject_found:
        findings.append(_finding(
            "warning",
            "No accept/reject controls found in banner markup",
            f"{page.url} appears to have a consent banner but no recognizable accept or "
            "reject button text was found — it may rely on non-standard wording or be "
            "rendered client-side after page load.",
            recommendation="Verify the banner exposes clearly labeled accept and reject actions.",
        ))

    if detection.reject_found and not detection.manage_found:
        findings.append(_finding(
            "info",
            "No granular preferences/manage option found",
            f"{page.url}'s banner offers accept/reject but no visible way to consent to "
            "individual cookie categories separately.",
            recommendation="Add a 'Manage preferences' option so visitors can opt into "
                            "specific categories (e.g. analytics but not marketing).",
        ))

    return findings


def _label_of(tag) -> str:
    text = tag.get_text(strip=True) if hasattr(tag, "get_text") else ""
    if not text:
        text = tag.get("aria-label") or tag.get("value") or ""
    return text.strip()


def _finding(severity: str, title: str, description: str, recommendation: str) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
