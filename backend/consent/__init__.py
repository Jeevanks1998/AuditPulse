"""
consent/

A dedicated, granular consent/cookie-compliance check package — one
file per concern — that gives services.audit_service.run_audit_pipeline
something real to write into models.consent.Consent instead of its
current `_write_consent_result` placeholder (random score, hardcoded
`_ga` cookie). Every check function returns findings in the same
{module, category, severity, title, description, recommendation} shape
services.audit_service / models.issue already persist, so nothing
downstream (Issue sync, report.html, history) needs to change to
consume them — same contract as seo/ and analytics/.

    banner        — is a consent banner/CMP present at all
    buttons       — accept/reject/manage button parity (dark-pattern check)
    consent_mode  — Google Consent Mode v1/v2 signal detection
    preferences   — persistent way to revisit/withdraw consent later
    cookies       — bridges the standalone cookies/ package (detector,
                    categories, expiry, validator, storage) into this
                    audit, plus pre-consent cookie exposure findings
    behavior      — derives banner_blocks_scripts_pre_consent from
                    consent_mode's declared default + (optionally)
                    network's live-captured evidence
    network       — OPTIONAL, Playwright-based: live capture of every
                    request fired before consent is given
    screenshots   — OPTIONAL, Playwright-based: element-clipped
                    screenshot of the banner itself for the report
    runtime       — OPTIONAL, Playwright-based: the click-through
                    counterpart to network — actually clicks Accept /
                    Reject / Personalize and re-captures cookies and
                    network traffic after each, so behavior.py's
                    verdict can be backed by what the controls really
                    do rather than only what fires before either is
                    clicked. See consent/runtime.py.
    consent_score — turns any list of these findings into a weighted
                    0-100 score (score_consent), and separately
                    assembles the full models.consent.Consent-ready row
                    (build_consent_summary)

banner/buttons/consent_mode/preferences/cookies are page-level and
synchronous, same as seo/ and analytics/ — everything they need is
already sitting in crawler.parser.ParsedPage plus, for cookies, the raw
Set-Cookie headers from that page's fetch. network/screenshots are the
exception: both require an actual browser (Playwright) and are always
optional, degrading to "no data" rather than raising when unavailable —
`analyze_site` below is the only entry point that touches them.

Usage — wiring this into the real pipeline (crawler.crawler.Crawler
already produces a ParsedPage per page; the caller also needs that
page's raw `Set-Cookie` header values, e.g. via
`response.headers.get_list("set-cookie")`, since crawler/crawler.py
doesn't currently expose them):

    from consent import run_page_checks, analyze_site

    findings = run_page_checks(page, cookies=page_cookies, first_party_hostname=hostname)

    # or, for the full picture including live pre-consent network capture:
    result = await analyze_site(audit.url, page, cookies=page_cookies, first_party_hostname=hostname)
    consent_row = Consent(audit_id=audit.id, **vars(result.summary))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from crawler.parser import ParsedPage

from consent.banner import BannerDetection, check_banner, detect_banner
from consent.behavior import BehaviorResult, check_behavior, evaluate_behavior
from consent.buttons import ButtonsDetection, check_buttons, detect_buttons
from consent.consent_mode import ConsentModeDetection, check_consent_mode, detect_consent_mode
from consent.consent_score import (
    ConsentScoreResult,
    ConsentSummary,
    build_consent_summary,
    score_consent,
)
from consent.cookies import analyze_cookies
from consent.network import PreConsentNetworkResult, capture_pre_consent_requests, check_pre_consent_network
from consent.preferences import PreferencesDetection, check_preferences, detect_preferences_link
from consent.runtime import ConsentRuntimeResult, check_runtime_consent, run_consent_runtime
from consent.screenshots import capture_banner_screenshot
from cookies.detector import Cookie
from cookies.storage import CookieAuditResult

__all__ = [
    "check_banner", "check_buttons", "check_consent_mode", "check_preferences",
    "check_behavior", "check_pre_consent_network", "check_runtime_consent",
    "detect_banner", "detect_buttons", "detect_consent_mode", "detect_preferences_link",
    "evaluate_behavior", "capture_pre_consent_requests", "capture_banner_screenshot",
    "run_consent_runtime",
    "BannerDetection", "ButtonsDetection", "ConsentModeDetection", "PreferencesDetection",
    "BehaviorResult", "PreConsentNetworkResult", "ConsentRuntimeResult",
    "score_consent", "ConsentScoreResult", "ConsentSummary", "build_consent_summary",
    "analyze_cookies",
    "run_page_checks", "analyze_site", "ConsentAuditResult",
]


def run_page_checks(
    page: ParsedPage,
    cookies: Optional[List[Cookie]] = None,
    first_party_hostname: Optional[str] = None,
    analytics_detected: bool = False,
) -> List[dict]:
    """
    Every static (non-Playwright) check in this package, run once for
    one already-fetched, already-parsed page. `cookies` should be that
    page's parsed Set-Cookie headers (cookies.detector.Cookie), if
    available — omit it to skip the cookie-specific findings.

    Uses an unverified `behavior` verdict (declared Consent Mode
    default only, no live network data) — see `analyze_site` for the
    verified version.
    """
    banner = detect_banner(page)
    buttons = detect_buttons(page)
    consent_mode = detect_consent_mode(page)
    behavior = evaluate_behavior(consent_mode=consent_mode, network=None)

    findings: List[dict] = []
    findings += check_banner(page)
    findings += check_buttons(page, banner_detected=banner.detected)
    findings += check_consent_mode(page, analytics_detected=analytics_detected)
    findings += check_preferences(page, banner_detected=banner.detected)
    findings += check_behavior(behavior, page.url)

    if cookies is not None:
        cookie_result = analyze_cookies(
            cookies, page=page, first_party_hostname=first_party_hostname,
            blocks_scripts_pre_consent=behavior.blocks_scripts_pre_consent if behavior.verified else None,
        )
        findings += cookie_result.findings

    return findings


@dataclass
class ConsentAuditResult:
    """Lightweight container mirroring analytics.AnalyticsAuditResult's shape."""
    findings: List[dict]
    score: ConsentScoreResult
    summary: ConsentSummary
    cookie_result: CookieAuditResult
    network_result: Optional[PreConsentNetworkResult] = None
    banner_screenshot_path: Optional[str] = None
    runtime_result: Optional[ConsentRuntimeResult] = None


async def analyze_site(
    url: str,
    page: ParsedPage,
    cookies: Optional[List[Cookie]] = None,
    first_party_hostname: Optional[str] = None,
    analytics_detected: bool = False,
    enable_live_checks: bool = True,
    capture_screenshot: bool = False,
    enable_runtime_checks: bool = False,
) -> ConsentAuditResult:
    """
    Full pipeline for one site: every static check plus, when
    `enable_live_checks` is True and Playwright is available, the live
    pre-consent network capture that lets `behavior`'s verdict be
    verified rather than merely declared. Falls back to the static-only
    picture automatically when Playwright isn't usable — see
    consent.network.capture_pre_consent_requests' own degrade path.

    `enable_runtime_checks=True` additionally runs consent.runtime's
    full click-through flow (Accept/Reject/Personalize + before/after
    cookie and network comparison). Off by default here since it opens
    two extra browser contexts and is noticeably slower than the rest
    of this pipeline — callers that want the full evidence picture
    (services.audit_service, the evidence-package export) should pass
    it explicitly.
    """
    banner = detect_banner(page)
    buttons = detect_buttons(page)
    consent_mode = detect_consent_mode(page)
    preferences = detect_preferences_link(page)

    network_result: Optional[PreConsentNetworkResult] = None
    if enable_live_checks:
        network_result = await capture_pre_consent_requests(url)

    behavior = evaluate_behavior(consent_mode=consent_mode, network=network_result)

    findings: List[dict] = []
    findings += check_banner(page)
    findings += check_buttons(page, banner_detected=banner.detected)
    findings += check_consent_mode(page, analytics_detected=analytics_detected)
    findings += check_preferences(page, banner_detected=banner.detected)
    findings += check_behavior(behavior, page.url)
    if network_result is not None:
        findings += check_pre_consent_network(network_result)

    cookie_result = analyze_cookies(
        cookies or [], page=page, first_party_hostname=first_party_hostname,
        blocks_scripts_pre_consent=behavior.blocks_scripts_pre_consent if behavior.verified else None,
    )
    findings += cookie_result.findings

    runtime_result: Optional[ConsentRuntimeResult] = None
    if enable_runtime_checks:
        runtime_result = await run_consent_runtime(url)
        findings += check_runtime_consent(runtime_result, url)

    score = score_consent(findings)
    summary = build_consent_summary(
        page=page,
        banner_detected=banner.detected,
        buttons=buttons,
        behavior=behavior,
        consent_mode=consent_mode,
        cookie_summary=cookie_result.summary,
        preferences_found=preferences.link_found or preferences.trigger_found,
        score_result=score,
        runtime_result=runtime_result,
    )

    banner_screenshot_path = None
    if capture_screenshot and enable_live_checks:
        banner_screenshot_path = await capture_banner_screenshot(url, filename_hint=url)
    if runtime_result is not None and runtime_result.initial_banner_screenshot:
        # runtime's own screenshot (taken mid-flow, same banner) is at least as good —
        # prefer it so we don't pay for two separate navigations when both are enabled.
        banner_screenshot_path = banner_screenshot_path or runtime_result.initial_banner_screenshot

    # Screenshots are only known *after* build_consent_summary ran above, so
    # they're set directly on the already-built summary here rather than
    # threaded through that call — this way a caller can still do a single
    # `Consent(audit_id=..., **vars(result.summary))` and get every field,
    # screenshots included, without a separate kwarg.
    summary.banner_screenshot_path = banner_screenshot_path
    if runtime_result is not None:
        summary.preferences_screenshot_path = runtime_result.preferences_screenshot
        summary.reject_screenshot_path = runtime_result.reject_screenshot
        summary.accept_screenshot_path = runtime_result.accept_screenshot

    return ConsentAuditResult(
        findings=findings,
        score=score,
        summary=summary,
        cookie_result=cookie_result,
        network_result=network_result,
        banner_screenshot_path=banner_screenshot_path,
        runtime_result=runtime_result,
    )
