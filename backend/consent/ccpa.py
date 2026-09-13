"""
consent/ccpa.py

CCPA/CPRA-specific detections that don't fit any existing consent/*
module:

  - a "Your Privacy Choices" / California-privacy-rights link — the
    CPRA-recognized opt-out entry point, distinct from GDPR's
    manage-preferences control that consent/preferences.py already
    looks for.
  - whether the page's own JS actually reads the Global Privacy
    Control (GPC) browser signal — CPRA requires businesses that
    sell/share personal information to treat GPC as a valid opt-out
    request, so a banner/link alone isn't enough; the page has to
    *listen* for navigator.globalPrivacyControl.

Both are static markup/script checks, same technique as
consent/consent_mode.py (script-text regex) and consent/preferences.py
(anchor-text regex) — no live browser needed for either. This module
only detects; consent.consent_score.build_ccpa_assessment turns these
detections (plus consent_score.detect_privacy_policy /
detect_ccpa_link and consent.preferences' result) into the CCPA
check breakdown, mirroring build_gdpr_assessment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from crawler.parser import ParsedPage

MODULE = "consent"
CATEGORY = "ccpa"

_PRIVACY_CHOICES_RE = re.compile(
    r"your privacy choices|california privacy rights|"
    r"do not sell (or share )?my (personal )?information|"
    r"\bccpa\b|cpra opt[-\s]?out",
    re.IGNORECASE,
)

# Best-effort static signal: the page's own JS references the GPC
# property at all. This can't confirm the read value actually gates
# anything (that would need a live pass), same caveat as
# consent/consent_mode.py's declared-default check — see
# CCPA_CHECK_LABELS["gpc_honored"] wording, which is deliberately
# phrased as "handling detected" rather than "honored" for this reason.
_GPC_JS_RE = re.compile(r"globalPrivacyControl", re.IGNORECASE)


@dataclass
class CcpaLinkDetection:
    found: bool = False
    text: Optional[str] = None
    href: Optional[str] = None


def detect_privacy_choices_link(page: ParsedPage) -> CcpaLinkDetection:
    """Finds a "Your Privacy Choices"-style link anywhere on the page (commonly footer nav)."""
    for tag in page.anchor_tags:
        text = tag.get_text(strip=True) or ""
        if _PRIVACY_CHOICES_RE.search(text):
            return CcpaLinkDetection(found=True, text=text, href=tag.get("href"))
    return CcpaLinkDetection()


def detect_gpc_handling(page: ParsedPage) -> bool:
    """True when any <script>'s text references navigator.globalPrivacyControl."""
    for tag in page.soup.find_all("script"):
        body = tag.string or tag.get_text() or ""
        if body and _GPC_JS_RE.search(body):
            return True
    return False
