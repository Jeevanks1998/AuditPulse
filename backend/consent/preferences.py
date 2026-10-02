"""
consent/preferences.py

GDPR requires withdrawing consent to be "as easy as giving it" — a
banner that only ever appears once, with no lasting way to change your
mind, fails that regardless of how good the banner itself is. This
checks for a persistent preferences/manage-cookies entry point: a
footer (or nav) link, or a CMP's known re-open trigger (OneTrust's
"#ot-sdk-btn" pattern and similar), that's still reachable after the
banner has been dismissed.

Two layers:

    static detection       — a footer/nav link or a CMP re-open trigger
                             exists in the markup (detect_preferences_link)
    + runtime verification — consent.runtime clicked the banner's
                             Manage/Personalize control: did a preference
                             panel with category choices actually appear?
                             (verify_preferences_runtime)

A link merely existing is not proof that preferences can be managed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "consent"
CATEGORY = "preferences"

_LINK_TEXT_RE = re.compile(
    r"cookie (settings|preferences|policy)|manage (cookies|preferences|consent)|"
    r"privacy (settings|preferences)|do not sell",
    re.IGNORECASE,
)

# Known CMP re-open trigger ids/classes, kept in sync with consent/banner.py's CMP list.
_CMP_TRIGGER_RE = re.compile(
    r"ot-sdk-btn|onetrust.*(settings|button)|CookiebotWidget|cky-btn-revisit|osano-cm-widget|"
    r"trustarc.*preferences|qc-cmp2-toggle-link|iubenda-cs-preferences-link|"
    r"cmplz-cookiebanner-manage|didomi-notice-learn-more-button",
    re.IGNORECASE,
)


@dataclass
class PreferencesDetection:
    link_found: bool = False
    trigger_found: bool = False
    link_text: Optional[str] = None
    link_href: Optional[str] = None
    # Runtime verification (None = not tested): Manage/Personalize was clicked
    # and a preference panel actually appeared.
    panel_verified: Optional[bool] = None
    panel_toggle_count: Optional[int] = None
    manage_control_label: Optional[str] = None


def verify_preferences_runtime(detection: PreferencesDetection, runtime_result=None) -> PreferencesDetection:
    """Adds consent.runtime's click-through verdict to the static detection (in place)."""
    if runtime_result is None or not getattr(runtime_result, "available", False):
        return detection
    if getattr(runtime_result, "manage_clicked", False):
        detection.panel_verified = runtime_result.personalize_exposes_controls is True
        panel = getattr(runtime_result, "preference_panel", None) or {}
        detection.panel_toggle_count = panel.get("toggle_count") if panel.get("banner_detected") else 0
        detection.manage_control_label = runtime_result.manage_clicked_label
    return detection


def detect_preferences_link(page: ParsedPage) -> PreferencesDetection:
    result = PreferencesDetection()

    for tag in page.anchor_tags:
        text = tag.get_text(strip=True)
        if text and _LINK_TEXT_RE.search(text):
            result.link_found = True
            result.link_text = text
            result.link_href = tag.get("href")
            break

    for tag in page.soup.find_all(True):
        for attr in ("id", "class"):
            value = tag.get(attr)
            if not value:
                continue
            joined = value if isinstance(value, str) else " ".join(value)
            if _CMP_TRIGGER_RE.search(joined):
                result.trigger_found = True
                break
        if result.trigger_found:
            break

    return result


def check_preferences(
    page: ParsedPage,
    banner_detected: bool = True,
    detection: Optional[PreferencesDetection] = None,
) -> List[dict]:
    if not banner_detected:
        return []

    detection = detection or detect_preferences_link(page)
    findings: List[dict] = []

    if detection.panel_verified is False:
        findings.append({
            "module": MODULE,
            "category": CATEGORY,
            "severity": "warning",
            "title": "Manage preferences did not open a preference panel",
            "description": f"{page.url}: the banner's '{detection.manage_control_label}' control was clicked in a "
                            "live browser, but no preference panel with category choices appeared.",
            "recommendation": "Make sure the Manage/Personalize control opens a working panel where "
                               "visitors can choose cookie categories.",
        })

    if detection.link_found or detection.trigger_found:
        return findings

    return findings + [{
        "module": MODULE,
        "category": CATEGORY,
        "severity": "warning",
        "title": "No persistent way to change cookie preferences",
        "description": f"{page.url} has a consent banner but no footer/nav link or CMP "
                        "trigger was found for revisiting cookie preferences after the "
                        "initial banner is dismissed.",
        "recommendation": "Add a persistent 'Cookie Settings' / 'Manage Preferences' link "
                           "(commonly in the footer) that reopens the consent panel.",
    }]
