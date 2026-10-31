"""
Consent and cookie checks, one file per topic:

  banner        - is there a cookie banner, and which tool (CMP)
  buttons       - Accept / Reject / Settings available and equally easy
  consent_mode  - Google Consent Mode signals
  preferences   - can visitors change their choice later
  cookies       - cookies set before consent
  behavior      - is tracking really held back until consent
  network       - live capture of requests before consent (browser)
  screenshots   - screenshot of the banner (browser)
  runtime       - clicks Accept / Reject / Settings and records what happens (browser)
  ccpa          - US privacy signals (Do Not Sell, GPC)
  region        - which region and laws apply
  consent_score - 0-100 score, GDPR / CCPA check lists and the saved summary

Browser checks are optional: if they can't run they report "not tested".
analyze_site() runs everything; run_page_checks() runs only static checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from crawler.parser import ParsedPage

from consent.banner import BannerDetection, check_banner, detect_banner
from consent.behavior import BehaviorResult, check_behavior, evaluate_behavior
from consent.buttons import ButtonsDetection, check_buttons, detect_buttons
from consent.ccpa import (
    CcpaLinkDetection, CcpaSignals, detect_ccpa_signals, detect_gpc_handling, detect_privacy_choices_link,
)
from consent.consent_mode import ConsentModeDetection, check_consent_mode, detect_consent_mode
from consent.consent_score import (
    CCPA_CHECK_LABELS,
    CCPA_CHECK_ORDER,
    DPDP_CHECK_LABELS,
    DPDP_CHECK_ORDER,
    GDPR_CHECK_LABELS,
    GDPR_CHECK_ORDER,
    CcpaAssessment,
    CcpaCheck,
    ConsentScoreResult,
    ConsentSummary,
    GdprAssessment,
    GdprCheck,
    build_ccpa_assessment,
    build_consent_summary,
    build_dpdp_assessment,
    build_gdpr_assessment,
    effective_buttons,
    resolve_banner_detection,
    score_consent,
)
from consent.cookies import analyze_cookies
from consent.network import PreConsentNetworkResult, capture_pre_consent_requests, check_pre_consent_network
from consent.preferences import (
    PreferencesDetection, check_preferences, detect_preferences_link, verify_preferences_runtime,
)
from consent.site_evidence import SiteEvidence, gather_site_evidence
from consent.region import (
    Applicability, RegionResult, detect_region, determine_applicability, refine_region,
)
from consent.runtime import ConsentRuntimeResult, check_runtime_consent, new_scan_id, run_consent_runtime
from consent.screenshots import capture_banner_screenshot
from cookies.detector import Cookie
from cookies.storage import CookieAuditResult

__all__ = [
    "check_banner", "check_buttons", "check_consent_mode", "check_preferences",
    "check_behavior", "check_pre_consent_network", "check_runtime_consent",
    "detect_banner", "detect_buttons", "detect_consent_mode", "detect_preferences_link",
    "verify_preferences_runtime",
    "evaluate_behavior", "capture_pre_consent_requests", "capture_banner_screenshot",
    "run_consent_runtime", "new_scan_id",
    "BannerDetection", "ButtonsDetection", "ConsentModeDetection", "PreferencesDetection",
    "BehaviorResult", "PreConsentNetworkResult", "ConsentRuntimeResult",
    "score_consent", "ConsentScoreResult", "ConsentSummary", "build_consent_summary",
    "GdprAssessment", "GdprCheck", "build_gdpr_assessment", "GDPR_CHECK_ORDER", "GDPR_CHECK_LABELS",
    "CcpaAssessment", "CcpaCheck", "build_ccpa_assessment", "CCPA_CHECK_ORDER", "CCPA_CHECK_LABELS",
    "CcpaLinkDetection", "CcpaSignals", "detect_ccpa_signals", "detect_privacy_choices_link", "detect_gpc_handling",
    "analyze_cookies",
    "RegionResult", "detect_region", "refine_region", "Applicability", "determine_applicability",
    "DPDP_CHECK_ORDER", "DPDP_CHECK_LABELS", "build_dpdp_assessment", "effective_buttons",
    "run_page_checks", "analyze_site", "ConsentAuditResult",
]


def run_page_checks(
    page: ParsedPage,
    cookies: Optional[List[Cookie]] = None,
    first_party_hostname: Optional[str] = None,
    analytics_detected: bool = False,
) -> List[dict]:
    """Static checks only (no browser) for one parsed page. analyze_site() is the full check."""
    banner = detect_banner(page)
    buttons = detect_buttons(page)
    consent_mode = detect_consent_mode(page)
    behavior = evaluate_behavior(consent_mode=consent_mode, network=None)

    findings: List[dict] = []
    findings += check_banner(page)
    findings += check_buttons(page, banner_detected=banner.detected, detection=buttons)
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
    """Result container: findings, score and summary."""
    findings: List[dict]
    score: ConsentScoreResult
    summary: ConsentSummary
    cookie_result: CookieAuditResult
    network_result: Optional[PreConsentNetworkResult] = None
    banner_screenshot_path: Optional[str] = None
    runtime_result: Optional[ConsentRuntimeResult] = None
    region: Optional[RegionResult] = None
    scan_id: Optional[str] = None
    pipeline: List[dict] = field(default_factory=list)
    # False when the live browser could not open the site: consent was not tested (no score).
    browser_tested: bool = True


def _browser_reached_site(live: bool, runtime: bool, static_banner: bool,
                          network_result, runtime_result) -> bool:
    """False only when live checks were on and no browser visit opened the page."""
    if not (live or runtime) or static_banner:
        return True
    if network_result is not None and network_result.available:
        return True
    if runtime_result is None:
        return not runtime
    if runtime_result.banner_detected:
        return True
    return any(cap.available for cap in (runtime_result.before_consent, runtime_result.before_accept,
                                         runtime_result.after_reject, runtime_result.after_accept))


_DPDP_FINDINGS = {
    "grievance_contact": ("warning", "No Grievance Officer contact in the privacy notice (DPDP Act)",
                          "Publish the name or title and contact details of a Grievance Officer / Data Protection "
                          "Officer who answers questions about personal data (DPDP Act s.8(10))."),
    "notice_purpose_stated": ("warning", "Privacy notice does not state what data is collected and why (DPDP Act)",
                              "List the personal data collected and the specific purpose for each, in clear language, "
                              "before or at the time consent is asked (DPDP Act s.5)."),
    "notice_rights_described": ("info", "Privacy notice does not explain data principal rights (DPDP Act)",
                                "Explain how people can access, correct and erase their data, withdraw consent, "
                                "nominate someone, and raise a grievance (DPDP Act ss.11–14)."),
}


def _dpdp_notice_findings(site_evidence, url: str) -> List[dict]:
    from consent.consent_score import _dpdp_notice_check

    out: List[dict] = []
    notice = getattr(site_evidence, "notice", None) if site_evidence is not None else None
    for key, (severity, title, rec) in _DPDP_FINDINGS.items():
        passed, ev = _dpdp_notice_check(key, site_evidence)
        if passed is False:
            out.append({
                "module": "consent", "category": "dpdp", "severity": severity, "title": title,
                "description": f"{ev.get('reason', '')} Notice checked: {notice.url if notice else url}.",
                "recommendation": rec,
            })
    return out


async def analyze_site(
    url: str,
    page: ParsedPage,
    cookies: Optional[List[Cookie]] = None,
    first_party_hostname: Optional[str] = None,
    analytics_detected: bool = False,
    enable_live_checks: bool = True,
    capture_screenshot: bool = False,
    enable_runtime_checks: bool = False,
    target_region: Optional[str] = None,
    scan_id: Optional[str] = None,
    cookie_scan_urls: Optional[List[str]] = None,
) -> ConsentAuditResult:
    """Full consent check, fresh every time:
      1 region, 2 banner, 3 controls, 4 requests before consent,
      5 cookies before consent, 6-7 Accept / Reject / Settings in a real browser,
      8 which laws apply, 9 assessment, 10 evidence, 11 screenshots.
    Browser steps that can't run are "not tested", never passed.
    """
    scan_id = scan_id or new_scan_id()
    started = datetime.now(timezone.utc)
    pipeline: List[dict] = []

    def step(n: int, name: str, status: str, detail: str = "") -> None:
        pipeline.append({"step": n, "name": name, "status": status, "detail": detail})

    # 1. Region ---------------------------------------------------------------
    # Global .com homepages rarely say where a business operates, so the
    # privacy notice and a few linked policy / about pages are read too
    # (consent.site_evidence) — for region evidence and the DPDP notice checks.
    site_evidence = None
    if enable_live_checks:
        try:
            site_evidence = await gather_site_evidence(url, page)
        except Exception:  # noqa: BLE001 — extra evidence is optional
            site_evidence = None
    region = detect_region(url, page, target_region, site=site_evidence)
    read = len(site_evidence.documents) if site_evidence else 0
    step(1, "Detect region", "done", f"{region.region_label} ({region.confidence} confidence)"
         + (f"; {read} linked page(s)/document(s) read" if read else ""))

    # 2. Banner (static; the browser check re-checks the rendered page)
    banner = detect_banner(page)
    step(2, "Detect banner", "done",
         ("static markup: " + (banner.cmp_name or "generic banner")) if banner.detected
         else "not in static HTML (checked again in the live browser)")

    # 3. Controls
    buttons = detect_buttons(page)
    consent_mode = detect_consent_mode(page)
    preferences = detect_preferences_link(page)
    ccpa_signals = detect_ccpa_signals(page)
    step(3, "Detect actual controls", "done",
         f"{len(buttons.controls)} control(s) in static banner markup" if buttons.container_found
         else "no banner controls in static HTML")

    # 4. Requests before consent
    network_result: Optional[PreConsentNetworkResult] = None
    if enable_live_checks:
        network_result = await capture_pre_consent_requests(url)
        step(4, "Capture pre-consent network", "done" if network_result.available else "not_tested",
             f"{len(network_result.requests)} request(s), {len(network_result.tracker_requests)} tracking"
             if network_result.available else (network_result.error or ""))
    else:
        step(4, "Capture pre-consent network", "skipped")

    behavior = evaluate_behavior(consent_mode=consent_mode, network=network_result)

    # 5. Cookies before consent (server headers; the browser check adds the rest)
    cookie_result = analyze_cookies(
        cookies or [], page=page, first_party_hostname=first_party_hostname,
        blocks_scripts_pre_consent=behavior.blocks_scripts_pre_consent if behavior.verified else None,
    )
    step(5, "Capture pre-consent cookies", "done", f"{len(cookies or [])} Set-Cookie header cookie(s)")

    # 6-7. Browser check: Accept / Reject / Settings
    runtime_result: Optional[ConsentRuntimeResult] = None
    if enable_runtime_checks:
        runtime_result = await run_consent_runtime(url, scan_id=scan_id, browse_urls=cookie_scan_urls)
        step(6, "Run runtime", "done" if runtime_result.available else "not_tested",
             f"{runtime_result.fresh_contexts} fresh browser context(s); banner "
             + ("detected" if runtime_result.banner_detected else "not detected")
             if runtime_result.available else (runtime_result.error or ""))
        states = []
        for label, cap in (("before consent", runtime_result.before_consent),
                           ("after reject", runtime_result.after_reject),
                           ("after accept", runtime_result.after_accept)):
            states.append(f"{label}: " + ("captured" if cap.available else f"not tested ({cap.error})"))
        step(7, "Capture Accept/Reject/Preferences states", "done", "; ".join(states)
             + ("; preferences panel " + ("verified" if runtime_result.personalize_exposes_controls else "not verified")
                if runtime_result.manage_clicked else ""))
        preferences = verify_preferences_runtime(preferences, runtime_result)
    else:
        step(6, "Run runtime", "skipped")
        step(7, "Capture Accept/Reject/Preferences states", "skipped")

    # 8. Which laws apply
    region = refine_region(region, runtime_result)
    step(8, "Determine applicable framework", "done",
         ", ".join(region.applicable_frameworks) if region.applicable_frameworks
         else "not determined — regional compliance not assessed")

    # 10. Findings (built before the score so the score includes them)
    findings: List[dict] = []
    banner_findings = check_banner(page)
    findings += banner_findings
    static_button_findings = check_buttons(page, banner_detected=banner.detected, detection=buttons)
    findings += static_button_findings
    findings += check_consent_mode(page, analytics_detected=analytics_detected)
    findings += check_preferences(page, banner_detected=banner.detected
                                  or bool(runtime_result and runtime_result.banner_detected),
                                  detection=preferences)
    findings += check_behavior(behavior, page.url)
    if network_result is not None:
        findings += check_pre_consent_network(network_result)
    findings += cookie_result.findings

    if runtime_result is not None:
        findings += check_runtime_consent(
            runtime_result, url,
            include_pre_consent=not (network_result is not None and network_result.available),
        )
        # The rendered page has a banner, so drop the static "no banner" finding.
        if banner_findings and resolve_banner_detection(banner.detected, runtime_result)[0]:
            findings = [f for f in findings if f not in banner_findings]
        # Use the rendered banner's buttons instead of the static ones.
        if runtime_result.available and runtime_result.banner_detected:
            findings = [f for f in findings if f not in static_button_findings]
            findings += check_buttons(page, banner_detected=True, detection=runtime_result.buttons_detection())

    # The live browser could not open the site at all (e.g. it timed out or was
    # blocked by a firewall): the banner, its buttons and the preferences panel
    # were never seen, so "no banner" would be a false finding. Report the
    # consent check as not tested instead, and leave it out of the score.
    browser_tested = _browser_reached_site(enable_live_checks, enable_runtime_checks,
                                           banner.detected, network_result, runtime_result)
    if not browser_tested:
        untested = {id(f) for f in banner_findings + static_button_findings}
        findings = [f for f in findings if id(f) not in untested
                    and f.get("category") not in ("banner", "buttons", "preferences")]
        reason = ((runtime_result.error if runtime_result and runtime_result.error else None)
                  or (network_result.error if network_result and network_result.error else None)
                  or "the page did not open in time")
        findings.append({
            "module": "consent",
            "category": "scan_coverage",
            "severity": "info",
            "title": "Consent banner could not be tested in a browser",
            "description": ("The browser could not open the site during this scan, so the consent banner, "
                            "its Accept / Reject buttons and the requests sent before consent were not checked. "
                            "The consent score is left out of this audit rather than shown as a failure. "
                            f"Reason: {str(reason)[:200]}"),
            "recommendation": ("Run the audit again. If it keeps happening, the site may be blocking the "
                               "scanner (a firewall or bot protection): ask for the scanner to be allowed."),
        })
        for entry in pipeline:
            if entry["step"] == 6:
                entry.update(status="not_tested", detail="browser could not open the site; consent not scored")

    # India DPDP notice checks become scored findings.
    if region.applies("dpdp"):
        findings += _dpdp_notice_findings(site_evidence, url)

    # 9. Score and assessments
    score = score_consent(findings)
    scan_meta = {
        "scan_id": scan_id,
        "started_at": started.isoformat(),
        "fresh": True,
        "fresh_browser_contexts": (runtime_result.fresh_contexts if runtime_result else 0)
                                  + (1 if network_result is not None and network_result.available else 0),
        "legs": list(runtime_result.leg_log) if runtime_result else [],
        "pipeline": pipeline,
        "browser_tested": browser_tested,
    }
    summary = build_consent_summary(
        page=page,
        banner_detected=banner.detected,
        buttons=buttons,
        behavior=behavior,
        consent_mode=consent_mode,
        cookie_summary=cookie_result.summary,
        preferences=preferences,
        score_result=score,
        runtime_result=runtime_result,
        network_result=network_result,
        region=region,
        ccpa_signals=ccpa_signals,
        scan_meta=scan_meta,
        site_evidence=site_evidence,
    )
    step(9, "Build applicable assessment", "done",
         ", ".join(region.applicable_frameworks) or "technical consent scan only")
    step(10, "Build evidence", "done", f"{len(findings)} finding(s), {len(summary.consent_controls)} control(s)")

    # 11. Screenshots
    banner_screenshot_path = None
    if runtime_result is not None and runtime_result.initial_banner_screenshot:
        banner_screenshot_path = runtime_result.initial_banner_screenshot
    elif capture_screenshot and enable_live_checks:
        banner_screenshot_path = await capture_banner_screenshot(url, filename_hint=url, scan_id=scan_id)

    summary.banner_screenshot_path = banner_screenshot_path
    if runtime_result is not None:
        summary.preferences_screenshot_path = runtime_result.preferences_screenshot
        summary.reject_screenshot_path = runtime_result.reject_screenshot
        summary.accept_screenshot_path = runtime_result.accept_screenshot
    shots = [p for p in (summary.banner_screenshot_path, summary.preferences_screenshot_path,
                         summary.reject_screenshot_path, summary.accept_screenshot_path) if p]
    step(11, "Build screenshots", "done" if shots else "not_tested", f"{len(shots)} screenshot(s)")
    scan_meta["finished_at"] = datetime.now(timezone.utc).isoformat()

    return ConsentAuditResult(
        browser_tested=browser_tested,
        findings=findings,
        score=score,
        summary=summary,
        cookie_result=cookie_result,
        network_result=network_result,
        banner_screenshot_path=banner_screenshot_path,
        runtime_result=runtime_result,
        region=region,
        scan_id=scan_id,
        pipeline=pipeline,
    )
