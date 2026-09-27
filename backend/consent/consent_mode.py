"""
consent/consent_mode.py

Detects Google Consent Mode (v2) signals: the `gtag('consent',
'default', {...})` call that must fire *before* any Google tag (GA4,
Ads, Floodlight) loads, and the later `gtag('consent', 'update', ...)`
call a CMP fires once the visitor actually answers the banner. Follows
the exact same regex-over-<script>-text technique as
analytics/ga4.py/gtm.py — this package deliberately doesn't duplicate
analytics/ga4.py's own detection, it only looks at the consent-specific
calls those files don't check.

Consent Mode v2 (2024+) requires two additional parameters —
`ad_user_data` and `ad_personalization` — on top of v1's four
(`ad_storage`, `analytics_storage`, `functionality_storage`,
`personalization_storage`); sites still missing them are running the
deprecated v1 shape, which Google has said will lose EEA ad-personalization
features.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

from crawler.parser import ParsedPage

MODULE = "consent"
CATEGORY = "consent_mode"

_DEFAULT_CALL_RE = re.compile(
    r"gtag\(\s*['\"]consent['\"]\s*,\s*['\"]default['\"]\s*,\s*\{([^}]*)\}", re.IGNORECASE | re.DOTALL,
)
_UPDATE_CALL_RE = re.compile(r"gtag\(\s*['\"]consent['\"]\s*,\s*['\"]update['\"]\s*,", re.IGNORECASE)
_PARAM_RE = re.compile(r"['\"]?(\w+)['\"]?\s*:\s*['\"](granted|denied)['\"]", re.IGNORECASE)

V1_PARAMS = {"ad_storage", "analytics_storage", "functionality_storage", "personalization_storage"}
V2_ONLY_PARAMS = {"ad_user_data", "ad_personalization"}


@dataclass
class ConsentModeDetection:
    default_call_found: bool = False
    update_call_found: bool = False
    default_params: Dict[str, str] = field(default_factory=dict)  # param -> "granted"|"denied"
    is_v2: bool = False


def detect_consent_mode(page: ParsedPage) -> ConsentModeDetection:
    result = ConsentModeDetection()

    for tag in page.soup.find_all("script"):
        body = tag.string or tag.get_text() or ""
        if not body:
            continue

        default_match = _DEFAULT_CALL_RE.search(body)
        if default_match:
            result.default_call_found = True
            for param_name, value in _PARAM_RE.findall(default_match.group(1)):
                result.default_params[param_name.lower()] = value.lower()

        if _UPDATE_CALL_RE.search(body):
            result.update_call_found = True

    result.is_v2 = V2_ONLY_PARAMS.issubset(result.default_params.keys())
    return result


def check_consent_mode(page: ParsedPage, analytics_detected: bool = False) -> List[dict]:
    """
    `analytics_detected` — pass analytics.detect_ga4(page).detected /
    detect_gtm(page).detected from the analytics/ package when
    available, so the "missing entirely" finding only fires on pages
    that actually load a Google tag; consent mode is meaningless
    without one.
    """
    detection = detect_consent_mode(page)
    findings: List[dict] = []

    if not detection.default_call_found:
        if analytics_detected:
            findings.append(_finding(
                "warning",
                "Google tag present without Consent Mode default state",
                f"{page.url} loads a Google tag (GA4/GTM) but no "
                "gtag('consent', 'default', ...) call was found before it — the tag has no "
                "pre-consent default state to fall back to.",
                recommendation="Fire gtag('consent', 'default', {...}) before any Google "
                                "tag loads, setting each storage type to 'denied' until the "
                                "visitor responds to the banner.",
            ))
        return findings

    if not detection.is_v2:
        missing = sorted(V2_ONLY_PARAMS - detection.default_params.keys())
        findings.append(_finding(
            "warning",
            "Consent Mode v1 detected — missing v2 parameters",
            f"{page.url}'s Consent Mode default call is missing {', '.join(missing)}, the "
            "parameters introduced in Consent Mode v2.",
            recommendation="Add ad_user_data and ad_personalization to the default/update "
                            "consent calls to move to Consent Mode v2.",
        ))

    missing_v1 = sorted(V1_PARAMS - detection.default_params.keys())
    if missing_v1:
        findings.append(_finding(
            "info",
            "Consent Mode default state omits some storage types",
            f"{page.url}'s default consent call doesn't set a value for: {', '.join(missing_v1)}.",
            recommendation="Set an explicit default ('granted' or 'denied') for every "
                            "storage type your tags use.",
        ))

    if not detection.update_call_found:
        findings.append(_finding(
            "warning",
            "No Consent Mode update call found",
            f"{page.url} sets a Consent Mode default state but no "
            "gtag('consent', 'update', ...) call was found — the CMP may not be wired up "
            "to actually update consent state once the visitor responds.",
            recommendation="Confirm the CMP calls gtag('consent', 'update', {...}) when "
                            "the visitor accepts/rejects/changes preferences.",
        ))

    return findings


def _finding(severity: str, title: str, description: str, recommendation: str) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
