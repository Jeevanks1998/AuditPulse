"""
consent/buttons.py

Looks at every <button>/<a>/<input> in the page for consent-banner-style
calls to action and classifies each into one of five buckets — accept,
reject, preferences, necessary_only, or unknown — then checks the
classic "dark pattern" complaint regulators (CNIL, ICO) have specifically
called out: an "Accept All" button that's one click away while
"Reject All" is missing, buried in a sub-menu, or requires more clicks
than accepting does.

Classification is a GLOBAL, page-wide text match (unlike
consent/runtime.py's live click-through pass, which only searches
*inside* an already-found consent container — see that module's
docstring). Because this scan isn't scoped to a container, it must be
conservative about which wordings it treats as consent-specific:

    A generic "OK" must never become Accept.
    A generic "Close" must never become Reject.
    A generic "Continue" must never become Accept.

Those three (and anything else that doesn't clearly match) fall through
to "unknown" rather than being guessed at. Matching a bare, ambiguous
word like that globally would misclassify the "OK" on an unrelated
alert dialog, or the "Continue" on a login form, as a consent decision
— and that false signal would then feed straight into the reject-parity
dark-pattern check below. Every pattern in this module therefore
requires an unambiguous consent-decision keyword (accept/allow/agree/
consent, reject/decline/refuse/deny, etc.) to actually appear in the
label; nothing here matches on filler words alone.

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

# ---------------------------------------------------------------------------
# Classification buckets.
#
# Exact-phrase allowlists first (normalized via _normalize below) so the
# specific wordings sites actually ship are recognized outright rather
# than relying on a regex to happen to cover them. Fallback regexes below
# then catch close variations (e.g. "Accept All Cookies", "Refuse Non-
# Essential", "Customize Settings") without needing every possible
# wording enumerated by hand — but every regex still requires one of the
# real consent-decision keywords to be present. Nothing here matches on
# "ok", "close", or "continue" alone; those are deliberately absent from
# every bucket and fall through to "unknown".

ACCEPT = "accept"
REJECT = "reject"
PREFERENCES = "preferences"
NECESSARY_ONLY = "necessary_only"
UNKNOWN = "unknown"

_ACCEPT_LABELS = {
    "accept",
    "accept all",
    "allow all",
    "i agree",
    "agree",
    "consent",
}
_REJECT_LABELS = {
    "reject",
    "reject all",
    "decline",
    "refuse",
    "refuse all",
    "deny",
}
_PREFERENCES_LABELS = {
    "manage preferences",
    "cookie settings",
    "customize",
    "customise",
    "settings",
    "manage consent",
}
_NECESSARY_ONLY_LABELS = {
    "only necessary",
    "necessary cookies only",
    "continue without accepting",
    "essential only",
}

# Fallback patterns for close variants. Each still anchors on a real
# consent-decision keyword (accept/allow/agree/consent, reject/decline/
# refuse/deny, manage/customize/settings, necessary/essential-only) — a
# bare "OK", "Close", or "Continue" contains none of these and will
# never match any of them, by design.
_ACCEPT_RE = re.compile(
    r"^\s*(i\s+)?(accept|allow|agree|consent)(\s+(all|everything|cookies))*\s*$",
    re.IGNORECASE,
)
_REJECT_RE = re.compile(
    r"^\s*(reject|decline|refuse|deny|disagree)"
    r"(\s+(all|everything|cookies|non[\s-]?essential))*\s*$",
    re.IGNORECASE,
)
_PREFERENCES_RE = re.compile(
    r"^\s*(manage\s+(preferences|consent|cookies)"
    r"|(cookie|privacy)\s+(settings|preferences|choices)"
    r"|customi[sz]e(\s+.*)?"
    r"|settings"
    r"|more options)\s*$",
    re.IGNORECASE,
)
_NECESSARY_ONLY_RE = re.compile(
    r"^\s*((only\s+)?necessary(\s+cookies)?(\s+only)?"
    r"|essential\s+only"
    r"|continue\s+without\s+accepting)\s*$",
    re.IGNORECASE,
)


def _normalize(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().lower())


def classify_button(label: str) -> str:
    """
    Classify a single button/link label into one of the five buckets:
    accept / reject / preferences / necessary_only / unknown.

    Order matters only in that necessary_only and reject are checked
    before the looser accept/preferences patterns, so phrases like
    "Continue Without Accepting" (contains neither "accept" as its own
    decision nor a reject keyword) resolve to necessary_only rather than
    falling through. In practice the keyword sets are disjoint — nothing
    in one bucket's regex can satisfy another's — so this mostly just
    keeps the check order readable.

    Anything that doesn't clearly match — including bare "OK", "Close",
    "Continue", "Submit", "Got it", etc. — returns "unknown". Those
    generic words are intentionally never added to any pattern above.
    """
    normalized = _normalize(label)
    if not normalized:
        return UNKNOWN

    if normalized in _NECESSARY_ONLY_LABELS or _NECESSARY_ONLY_RE.match(normalized):
        return NECESSARY_ONLY
    if normalized in _REJECT_LABELS or _REJECT_RE.match(normalized):
        return REJECT
    if normalized in _ACCEPT_LABELS or _ACCEPT_RE.match(normalized):
        return ACCEPT
    if normalized in _PREFERENCES_LABELS or _PREFERENCES_RE.match(normalized):
        return PREFERENCES
    return UNKNOWN


@dataclass
class ButtonsDetection:
    accept_found: bool = False
    reject_found: bool = False
    manage_found: bool = False
    necessary_only_found: bool = False

    accept_labels: List[str] = field(default_factory=list)
    reject_labels: List[str] = field(default_factory=list)
    manage_labels: List[str] = field(default_factory=list)
    necessary_only_labels: List[str] = field(default_factory=list)
    unknown_labels: List[str] = field(default_factory=list)

    @property
    def has_reject_parity(self) -> bool:
        """
        True when the visitor has *some* one-click way to decline
        non-essential cookies — a true "Reject" control, or a
        "Necessary Only" / "Continue Without Accepting" control, which
        serves the same functional purpose even though it's classified
        separately above. Visual weight/click-depth isn't measured here
        (see this module's docstring).
        """
        return self.accept_found and (self.reject_found or self.necessary_only_found)


def detect_buttons(page: ParsedPage) -> ButtonsDetection:
    result = ButtonsDetection()
    candidates = page.soup.find_all(["button", "a", "input"])

    for tag in candidates:
        label = _label_of(tag)
        if not label:
            continue

        category = classify_button(label)

        if category == ACCEPT:
            result.accept_found = True
            result.accept_labels.append(label)
        elif category == REJECT:
            result.reject_found = True
            result.reject_labels.append(label)
        elif category == PREFERENCES:
            result.manage_found = True
            result.manage_labels.append(label)
        elif category == NECESSARY_ONLY:
            result.necessary_only_found = True
            result.necessary_only_labels.append(label)
        else:
            result.unknown_labels.append(label)

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

    if detection.accept_found and not (detection.reject_found or detection.necessary_only_found):
        findings.append(_finding(
            "critical",
            "Accept-all button present with no equivalent reject option",
            f"{page.url}'s consent banner offers a one-click 'Accept' but no equally "
            "direct way to reject non-essential cookies — a pattern GDPR regulators "
            "(CNIL, ICO) have explicitly flaged as non-compliant.",
            recommendation="Offer 'Reject All' with the same prominence and click-depth as 'Accept All'.",
        ))
    elif not detection.accept_found and not detection.reject_found and not detection.necessary_only_found:
        findings.append(_finding(
            "warning",
            "No accept/reject controls found in banner markup",
            f"{page.url} appears to have a consent banner but no recognizable accept or "
            "reject button text was found — it may rely on non-standard wording or be "
            "rendered client-side after page load.",
            recommendation="Verify the banner exposes clearly labeled accept and reject actions.",
        ))

    if (detection.reject_found or detection.necessary_only_found) and not detection.manage_found:
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
