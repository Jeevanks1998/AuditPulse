"""
consent/network.py

Live capture of every network request a page fires *before* any
consent-banner button is clicked. This is the one check in consent/
that can't be done statically — a page's HTML can declare a perfectly
compliant Consent Mode default and still load a tracker's script
immediately via a bare, unconditional <script src="..."> tag, and the
only way to know is to actually load the page and watch the network
tab, the way a regulator's automated crawler (e.g. the CNIL's) does.

Playwright is an optional, heavy dependency here for the exact reason
it is in crawler/screenshots.py: every entry point degrades to
returning an empty/None result rather than raising when the package
isn't installed or `playwright install` hasn't been run, so a missing
browser binary can never take down the rest of the consent audit.
consent/behavior.py and consent/consent_score.py both already treat
"no data available" as "skip this check" rather than "fail it", so
degrading gracefully here doesn't manufacture a false pass either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse

from config.logging import logger

NAVIGATION_TIMEOUT_MS = 20_000
SETTLE_MS = 1_500  # brief idle window after load to catch requests fired from a setTimeout/deferred script

# Known third-party tracker/ad domains worth calling out specifically
# when seen pre-consent. Not exhaustive — anything third-party at all
# is still reported, this list only upgrades severity/labeling.
KNOWN_TRACKER_DOMAINS = {
    "google-analytics.com": "Google Analytics",
    "analytics.google.com": "Google Analytics",
    "googletagmanager.com": "Google Tag Manager",
    "doubleclick.net": "Google Ads / DoubleClick",
    "googlesyndication.com": "Google AdSense",
    "connect.facebook.net": "Meta Pixel",
    "facebook.com": "Meta",
    "ads-twitter.com": "Twitter/X Ads",
    "analytics.tiktok.com": "TikTok Pixel",
    "hotjar.com": "Hotjar",
    "clarity.ms": "Microsoft Clarity",
    "hs-analytics.net": "HubSpot",
    "adsrvr.org": "The Trade Desk",
}


@dataclass
class NetworkRequest:
    url: str
    domain: str
    resource_type: str  # "script" | "xhr" | "image" | ... (Playwright's request.resource_type)
    is_third_party: bool
    tracker_name: Optional[str] = None


@dataclass
class PreConsentNetworkResult:
    available: bool = False  # False when Playwright wasn't usable — callers must not treat this as "clean"
    requests: List[NetworkRequest] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def third_party_requests(self) -> List[NetworkRequest]:
        return [r for r in self.requests if r.is_third_party]

    @property
    def tracker_requests(self) -> List[NetworkRequest]:
        return [r for r in self.requests if r.tracker_name]


async def capture_pre_consent_requests(url: str, settle_ms: int = SETTLE_MS) -> PreConsentNetworkResult:
    """
    Loads `url` in a fresh, cookie-less browser context and records every
    request fired up to `settle_ms` after load — deliberately never
    clicks any banner button, since the whole point is "what fires
    before the visitor answers".
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("consent/network.py: playwright not installed — skipping pre-consent capture")
        return PreConsentNetworkResult(available=False, error="playwright not installed")

    hostname = urlparse(url).hostname or ""
    captured: List[NetworkRequest] = []

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                context = await browser.new_context()
                page = await context.new_page()

                page.on("request", lambda request: captured.append(_classify(request.url, request.resource_type, hostname)))

                await page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
                await page.wait_for_timeout(settle_ms)
            finally:
                await browser.close()

        return PreConsentNetworkResult(available=True, requests=captured)

    except Exception as exc:  # noqa: BLE001 — a failed capture should never break the audit
        logger.warning(f"consent/network.py: failed to capture {url}: {exc}")
        return PreConsentNetworkResult(available=False, error=str(exc))


def _classify(request_url: str, resource_type: str, first_party_hostname: str) -> NetworkRequest:
    domain = urlparse(request_url).hostname or ""
    third_party = bool(domain) and not (
        domain == first_party_hostname or domain.endswith("." + first_party_hostname)
    )
    tracker_name = None
    for known_domain, name in KNOWN_TRACKER_DOMAINS.items():
        if domain == known_domain or domain.endswith("." + known_domain):
            tracker_name = name
            break

    return NetworkRequest(
        url=request_url, domain=domain, resource_type=resource_type,
        is_third_party=third_party, tracker_name=tracker_name,
    )


def check_pre_consent_network(result: PreConsentNetworkResult) -> List[dict]:
    """
    Findings from an already-captured PreConsentNetworkResult. Returns
    nothing when `available` is False — an unavailable capture is a
    missing check, not a passing one, so it must not silently affect
    consent_score's weighting either (see consent/consent_score.py).
    """
    if not result.available:
        return []

    findings: List[dict] = []
    trackers = result.tracker_requests
    if trackers:
        names = sorted({r.tracker_name for r in trackers})
        findings.append({
            "module": "consent",
            "category": "network",
            "severity": "critical",
            "title": "Known trackers fire before consent is given",
            "description": f"{len(trackers)} request(s) to known tracker(s) ({', '.join(names)}) "
                            "were observed before any consent action was taken.",
            "recommendation": "Block third-party tracker scripts until the visitor has "
                               "explicitly consented — load them conditionally after "
                               "gtag('consent', 'update', {...granted...}) or an equivalent CMP callback.",
        })

    other_third_party = [r for r in result.third_party_requests if not r.tracker_name]
    if other_third_party:
        domains = sorted({r.domain for r in other_third_party})[:5]
        findings.append({
            "module": "consent",
            "category": "network",
            "severity": "info",
            "title": "Other third-party requests fire before consent",
            "description": f"{len(other_third_party)} request(s) to unrecognized third-party "
                            f"domain(s) ({', '.join(domains)}) fired before consent.",
            "recommendation": "Review whether these requests set cookies or transmit "
                               "personal data, and gate them behind consent if so.",
        })

    return findings
