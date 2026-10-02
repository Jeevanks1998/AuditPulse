"""
consent/ccpa.py

Technical CCPA/CPRA *signals* only:

  - a "Your Privacy Choices" / California-privacy-rights link
  - a "Do Not Sell or Share My Personal Information" link
  - whether the page's own JS reads the Global Privacy Control (GPC)
    signal (navigator.globalPrivacyControl)

This module never decides whether CCPA applies. The architecture is:

    ccpa.py           →  technical CCPA signals      (detect_ccpa_signals)
    region.py         →  CCPA applicability          (California candidate?)
    consent_score.py  →  CCPA assessment             (only when applicable)

All checks are static markup/script reads — no live browser needed.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
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


_DO_NOT_SELL_RE = re.compile(r"do not sell (or share )?my (personal )?information", re.IGNORECASE)


def detect_do_not_sell_link(page: ParsedPage) -> bool:
    """A "Do Not Sell (or Share) My Personal Information" link anywhere on the page."""
    for tag in page.anchor_tags:
        if _DO_NOT_SELL_RE.search(tag.get_text(strip=True) or ""):
            return True
    return False


@dataclass
class CcpaSignals:
    """Every technical CCPA signal for one page. Says nothing about applicability."""
    privacy_choices: CcpaLinkDetection
    do_not_sell_link: bool = False
    gpc_handling: bool = False

    @property
    def any_signal(self) -> bool:
        return self.privacy_choices.found or self.do_not_sell_link or self.gpc_handling

    def as_dict(self) -> dict:
        return {
            "privacy_choices_link": asdict(self.privacy_choices),
            "do_not_sell_link": self.do_not_sell_link,
            "gpc_handling": self.gpc_handling,
        }


def detect_ccpa_signals(page: ParsedPage) -> CcpaSignals:
    return CcpaSignals(
        privacy_choices=detect_privacy_choices_link(page),
        do_not_sell_link=detect_do_not_sell_link(page),
        gpc_handling=detect_gpc_handling(page),
    )
