"""
Does the site really hold tracking back until consent, or only show a banner?

Two signals: the Consent Mode default (a claim in the page's code) and, when
available, the live capture of requests before consent (proof). With only
the claim, the result is marked unverified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from consent.consent_mode import ConsentModeDetection
from consent.network import PreConsentNetworkResult

MODULE = "consent"
CATEGORY = "behavior"


@dataclass
class BehaviorResult:
    blocks_scripts_pre_consent: bool  # best available answer (saved to the database)
    verified: bool                    # True only when live requests confirmed it
    declared_denied_by_default: bool  # from the Consent Mode default call


def evaluate_behavior(
    consent_mode: Optional[ConsentModeDetection] = None,
    network: Optional[PreConsentNetworkResult] = None,
) -> BehaviorResult:
    declared_denied = False
    if consent_mode is not None and consent_mode.default_call_found:
        # No "granted" in the default means tracking is declared off until consent.
        declared_denied = "granted" not in consent_mode.default_params.values()

    if network is not None and network.available:
        verified_clean = len(network.tracker_requests) == 0
        return BehaviorResult(
            blocks_scripts_pre_consent=verified_clean,
            verified=True,
            declared_denied_by_default=declared_denied,
        )

    # No live data: use the declared default, marked unverified.
    return BehaviorResult(
        blocks_scripts_pre_consent=declared_denied,
        verified=False,
        declared_denied_by_default=declared_denied,
    )


def check_behavior(result: BehaviorResult, page_url: str) -> List[dict]:
    if result.blocks_scripts_pre_consent and result.verified:
        return []

    if not result.blocks_scripts_pre_consent:
        severity = "critical" if result.verified else "warning"
        confidence = "confirmed via live network capture" if result.verified \
            else "based on the page's own declared Consent Mode default only — not independently verified"
        return [{
            "module": MODULE,
            "category": CATEGORY,
            "severity": severity,
            "title": "Scripts are not held back until consent is given",
            "description": f"{page_url} does not appear to block non-essential scripts before "
                            f"consent ({confidence}).",
            "recommendation": "Gate non-essential scripts (analytics, ads, embeds) behind an "
                               "explicit consent check rather than loading them unconditionally.",
        }]

    # blocks scripts, but unverified
    return [{
        "module": MODULE,
        "category": CATEGORY,
        "severity": "info",
        "title": "Pre-consent script blocking declared but not independently verified",
        "description": f"{page_url} declares a 'denied' Consent Mode default, but this "
                        "wasn't confirmed by live network capture (Playwright unavailable).",
        "recommendation": "Enable the live network check to confirm no tracker requests "
                           "actually fire before consent, or verify manually with browser dev tools.",
    }]
