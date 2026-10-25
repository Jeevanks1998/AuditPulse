"""
Can visitors change their cookie choice later? (GDPR: withdrawing must be as
easy as giving consent.)

Static: a footer/nav link or a CMP re-open button exists in the HTML.
Browser: clicking Settings really opened a panel with category choices.
A link alone doesn't prove preferences can be managed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "consent"
CATEGORY = "preferences"

_LINK_TEXT_RE = re.compile(
    r"cookie (settings|preferences|policy|choices)|cookies? (settings|preferences|choices)|"
    r"manage (cookies|preferences|consent|cookie settings)|personali[sz]e (cookies|cookie settings|your cookies)|"
    r"(change|update|review) (your )?(cookie|consent|privacy) (settings|preferences|choices)|"
    r"privacy (settings|preferences|choices)|your privacy choices|do not sell|"
    r"cookie[- ]einstellungen|datenschutz[- ]einstellungen|g[ée]rer (les )?cookies|param[eè]tres (des )?cookies|"
    r"preferenze (dei |sui )?cookie|impostazioni (dei )?cookie|scelte sui cookie|"
    r"configuraci[óo]n de cookies|preferencias de cookies|cookie[- ]instellingen",
    re.IGNORECASE,
)

# Known CMP re-open buttons (keep in sync with banner.py).
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
    # Browser check (None = not tested): Settings was clicked and a panel appeared.
    panel_verified: Optional[bool] = None
    panel_toggle_count: Optional[int] = None
    manage_control_label: Optional[str] = None


def verify_preferences_runtime(detection: PreferencesDetection, runtime_result=None) -> PreferencesDetection:
    """Adds the browser check result to the static detection."""
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

    # Links and buttons: many sites re-open the panel from a footer <button>.
    from consent.buttons import MANAGE_PREFERENCES, classify_label
    for tag in page.soup.find_all(["a", "button"]) + page.soup.find_all(attrs={"role": "button"}):
        text = tag.get_text(" ", strip=True) or tag.get("aria-label") or ""
        if not text or len(text) > 80:
            continue
        if _LINK_TEXT_RE.search(text) or classify_label(text) == MANAGE_PREFERENCES:
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
