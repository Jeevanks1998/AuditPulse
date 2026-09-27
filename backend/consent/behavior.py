"""
consent/behavior.py

Answers the single question models.consent.Consent.banner_blocks_scripts_pre_consent
exists to store: does this site actually hold non-essential scripts
back until the visitor consents, or does it just show a banner while
tracking regardless (the single most common real-world consent
violation).

Combines two independent signals, neither of which is trustworthy
alone:

  - static: consent.consent_mode's default-call detection — a
    Consent Mode default of 'denied' for storage types is a strong
    declared-intent signal, but it's just a claim in the page's own
    JS; nothing stops a site from setting it and loading trackers
    unconditionally anyway.
  - live (optional): consent.network's pre-consent request capture —
    ground truth for what actually fired, but requires Playwright and
    is skipped gracefully when unavailable (see consent/network.py).

When only the static signal is available, the verdict is "declared but
unverified" rather than a hard pass — see `verified` on the result.
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
    blocks_scripts_pre_consent: bool  # best-available verdict — what models.consent.Consent stores
    verified: bool                    # True only when live network data backed the verdict
    declared_denied_by_default: bool  # from Consent Mode's default call, if present


def evaluate_behavior(
    consent_mode: Optional[ConsentModeDetection] = None,
    network: Optional[PreConsentNetworkResult] = None,
) -> BehaviorResult:
    declared_denied = False
    if consent_mode is not None and consent_mode.default_call_found:
        # "denied" (or absent, which the platform treats as denied) across storage types
        # counts as declaring pre-consent blocking; any explicit "granted" does not.
        declared_denied = "granted" not in consent_mode.default_params.values()

    if network is not None and network.available:
        verified_clean = len(network.tracker_requests) == 0
        return BehaviorResult(
            blocks_scripts_pre_consent=verified_clean,
            verified=True,
            declared_denied_by_default=declared_denied,
        )

    # No live data — fall back to the declared signal, flagged as unverified.
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

    # blocks_scripts_pre_consent True but unverified
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
