"""
Analytics checks: which tracking tools a page has and whether they work.

One detector per tool (ga4, gtm, adobe, piano, clarity, hotjar, meta_pixel,
linkedin, tiktok), each with detect_x() (what was found) and check_x()
(findings). Also:
  data_layer       - dataLayer set-up and pushes
  duplicate_tags   - the same tag loaded twice or with two IDs
  analytics_score  - 0-100 score and the summary saved to the database
  runtime          - optional real-browser check that tags actually fire
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from crawler.parser import ParsedPage

from analytics.adobe import AdobeDetection, check_adobe, detect_adobe
from analytics.analytics_score import (
    AnalyticsScoreResult,
    AnalyticsSummary,
    PageAnalyticsResult,
    build_analytics_summary,
    check_consent_analytics_correlation,
    check_cross_page_consistency,
    compute_site_coverage,
    score_analytics,
    score_site_analytics,
)
from analytics.clarity import ClarityDetection, check_clarity, detect_clarity
from analytics.data_layer import DataLayerDetection, check_data_layer, detect_data_layer
from analytics.duplicate_tags import TrackerLoad, check_duplicate_tags
from analytics.ga4 import GA4Detection, check_ga4, detect_ga4
from analytics.gtm import GTMDetection, check_gtm, detect_gtm
from analytics.hotjar import HotjarDetection, check_hotjar, detect_hotjar
from analytics.linkedin import LinkedInDetection, check_linkedin, detect_linkedin
from analytics.meta_pixel import MetaPixelDetection, check_meta_pixel, detect_meta_pixel
from analytics.piano import PianoDetection, check_piano, detect_piano
from analytics.runtime import (
    AnalyticsRuntimeResult,
    check_runtime_analytics,
    merge_static_detected_vendors,
    run_analytics_runtime,
)
from analytics.tagcommander import TagCommanderDetection, check_tagcommander, detect_tagcommander
from analytics.tiktok import TikTokDetection, check_tiktok, detect_tiktok
from crawler.parser import parse_html

__all__ = [
    "check_ga4", "check_gtm", "check_adobe", "check_piano", "check_clarity",
    "check_hotjar", "check_meta_pixel", "check_linkedin", "check_tiktok",
    "check_data_layer", "check_duplicate_tags", "check_runtime_analytics",
    "detect_ga4", "detect_gtm", "detect_adobe", "detect_piano", "detect_clarity",
    "detect_hotjar", "detect_meta_pixel", "detect_linkedin", "detect_tiktok",
    "detect_data_layer", "run_analytics_runtime", "merge_static_detected_vendors",
    "GA4Detection", "GTMDetection", "AdobeDetection", "PianoDetection",
    "ClarityDetection", "HotjarDetection", "MetaPixelDetection", "LinkedInDetection",
    "TikTokDetection", "DataLayerDetection", "TrackerLoad", "AnalyticsRuntimeResult",
    "score_analytics", "AnalyticsScoreResult", "AnalyticsSummary", "build_analytics_summary",
    "run_page_checks", "analyze_page", "analyze_page_runtime", "analyze_site", "AnalyticsAuditResult",
    "PageAnalyticsResult", "analyze_page_for_site", "check_cross_page_consistency",
    "score_site_analytics", "compute_site_coverage", "check_consent_analytics_correlation",
]


def run_page_checks(page: ParsedPage) -> List[dict]:
    """Runs every static check on one parsed page."""
    ga4 = detect_ga4(page)
    gtm = detect_gtm(page)
    adobe = detect_adobe(page)
    piano = detect_piano(page)
    clarity = detect_clarity(page)
    hotjar = detect_hotjar(page)
    meta_pixel = detect_meta_pixel(page)
    linkedin = detect_linkedin(page)
    tiktok = detect_tiktok(page)
    data_layer = detect_data_layer(page)

    findings: List[dict] = []
    findings += check_ga4(page)
    findings += check_gtm(page)
    findings += check_adobe(page)
    findings += check_piano(page)
    findings += check_clarity(page)
    findings += check_hotjar(page)
    findings += check_meta_pixel(page)
    findings += check_linkedin(page)
    findings += check_tiktok(page)
    findings += check_data_layer(page, gtm_detected=gtm.detected)
    findings += check_duplicate_tags(page, _build_tracker_loads(
        ga4, gtm, adobe, piano, clarity, hotjar, meta_pixel, linkedin, tiktok,
    ))
    return findings


@dataclass
class AnalyticsAuditResult:
    """Result container: findings, score and summary."""
    findings: List[dict]
    score: AnalyticsScoreResult
    summary: AnalyticsSummary
    # True when the raw HTML has no tracking and every tool was only seen in the
    # browser (added by JavaScript). Raw-HTML checks of other pages then prove nothing.
    tags_injected_by_js: bool = False


def analyze_page(page: ParsedPage) -> AnalyticsAuditResult:
    """Runs every detector once and returns findings, score and summary for one page."""
    ga4 = detect_ga4(page)
    gtm = detect_gtm(page)
    adobe = detect_adobe(page)
    piano = detect_piano(page)
    clarity = detect_clarity(page)
    hotjar = detect_hotjar(page)
    meta_pixel = detect_meta_pixel(page)
    linkedin = detect_linkedin(page)
    tiktok = detect_tiktok(page)
    data_layer = detect_data_layer(page)

    findings: List[dict] = []
    findings += check_ga4(page)
    findings += check_gtm(page)
    findings += check_adobe(page)
    findings += check_piano(page)
    findings += check_clarity(page)
    findings += check_hotjar(page)
    findings += check_meta_pixel(page)
    findings += check_linkedin(page)
    findings += check_tiktok(page)
    findings += check_data_layer(page, gtm_detected=gtm.detected)
    findings += check_duplicate_tags(page, _build_tracker_loads(
        ga4, gtm, adobe, piano, clarity, hotjar, meta_pixel, linkedin, tiktok,
    ))

    score = score_analytics(findings)
    summary = build_analytics_summary(
        ga4_detection=ga4,
        gtm_detection=gtm,
        data_layer_detection=data_layer,
        meta_pixel_detection=meta_pixel,
        tiktok_detection=tiktok,
        other_detections={"adobe": adobe, "piano": piano, "clarity": clarity,
                           "hotjar": hotjar, "linkedin": linkedin},
        score_result=score,
    )

    return AnalyticsAuditResult(findings=findings, score=score, summary=summary)


def analyze_page_for_site(page: ParsedPage, url: str) -> PageAnalyticsResult:
    """Static-only check for one page of a full-site audit. The browser check runs
    once, on the homepage, to keep full-site audits fast.
    """
    result = analyze_page(page)
    return PageAnalyticsResult(
        url=url,
        trackers_detected=result.summary.trackers_detected,
        vendor_configs=result.summary.vendor_configs,
        score=result.score.overall,
        findings=result.findings,
    )


async def analyze_page_runtime(url: str, page: ParsedPage):
    """Opens `url` in a real browser and flags tags that are in the page code but
    never fire. Returns (runtime_result, findings); if the browser can't run,
    available=False and no findings (never a false pass).
    """
    static_detected = {
        "ga4": detect_ga4(page).detected,
        "gtm": detect_gtm(page).detected,
        "adobe": detect_adobe(page).detected,
        "piano": detect_piano(page).detected,
        "clarity": detect_clarity(page).detected,
        "hotjar": detect_hotjar(page).detected,
        "meta_pixel": detect_meta_pixel(page).detected,
        "linkedin": detect_linkedin(page).detected,
        "tiktok": detect_tiktok(page).detected,
    }
    runtime_result = await run_analytics_runtime(url)
    findings = check_runtime_analytics(runtime_result, url, static_detected=static_detected)
    merge_static_detected_vendors(runtime_result, static_detected)
    return runtime_result, findings


async def analyze_site(url: str, page: ParsedPage, enable_runtime_checks: bool = True) -> AnalyticsAuditResult:
    """Static checks plus (optionally) the live browser check, combined into one
    score and summary. Used by the audit pipeline.
    """
    # 1. Browser check first: it also returns the page as rendered after
    #    accepting the cookie banner.
    runtime_result = None
    rendered_page: Optional[ParsedPage] = None
    if enable_runtime_checks:
        runtime_result = await run_analytics_runtime(url)
        rendered_html = getattr(runtime_result, "_rendered_html", None)
        if runtime_result.available and rendered_html:
            try:
                rendered_page = parse_html(url, rendered_html)
            except Exception:  # noqa: BLE001 — fall back to the raw HTML only
                rendered_page = None

    # 2. Pick which HTML to scan. JavaScript-built sites have no tracking code in
    #    the raw HTML, so use the rendered page unless the raw HTML shows as much.
    def _detected_count(pg: ParsedPage) -> int:
        dets = (detect_ga4(pg), detect_gtm(pg), detect_adobe(pg), detect_piano(pg), detect_clarity(pg),
                detect_hotjar(pg), detect_meta_pixel(pg), detect_linkedin(pg), detect_tiktok(pg),
                detect_tagcommander(pg))
        return sum(1 for d in dets if d.detected) + (1 if detect_data_layer(pg).present else 0)

    raw_detected = _detected_count(page)
    if rendered_page is not None and _detected_count(rendered_page) > raw_detected:
        page = rendered_page

    ga4 = detect_ga4(page)
    gtm = detect_gtm(page)
    adobe = detect_adobe(page)
    piano = detect_piano(page)
    clarity = detect_clarity(page)
    hotjar = detect_hotjar(page)
    meta_pixel = detect_meta_pixel(page)
    linkedin = detect_linkedin(page)
    tiktok = detect_tiktok(page)
    tagcommander = detect_tagcommander(page)
    data_layer = detect_data_layer(page)

    # A dataLayer created at runtime only exists in the browser.
    globals_ = (runtime_result.page_globals or {}) if runtime_result is not None else {}
    _CMP_EVENT = re.compile(r"onetrust|optanon|cookiebot|didomi|usercentrics|axeptio|tc_privacy|consent|cmp", re.I)
    meaningful = globals_.get("dataLayer_meaningful", globals_.get("dataLayer"))
    if not data_layer.present and isinstance(meaningful, int) and meaningful > 0:
        data_layer.present = True
    elif (data_layer.present and isinstance(meaningful, int) and meaningful == 0
          and all(_CMP_EVENT.search(n or "") for n in data_layer.event_names)):
        # Only the cookie banner writes to dataLayer: that's consent bookkeeping, not analytics.
        data_layer.present = False
    if not tagcommander.detected and globals_.get("tagcommander"):
        tagcommander.detected = True
        tagcommander.tc_api_found = True
    if (runtime_result is not None and getattr(runtime_result, "available", False)
            and globals_.get("tagcommander") is False and not tagcommander.script_tag_count
            and not tagcommander.container_ids):
        # window.tC came from the TrustCommander banner, not a TagCommander container.
        tagcommander.detected = False
    # Piano loaded by a tag manager after consent only shows up in the browser.
    if globals_.get("piano") or globals_.get("piano_site"):
        piano.detected = True
        piano.uses_current_sdk = piano.uses_current_sdk or bool(globals_.get("piano_site"))
        site = str(globals_.get("piano_site") or "").strip()
        if site and site not in piano.site_ids:
            piano.site_ids.append(site)
    if runtime_result is not None and getattr(runtime_result, "vendors", None):
        pv = runtime_result.vendors.get("piano")
        if pv is not None and getattr(pv, "captured_request_count", 0) > 0:
            piano.detected = True
            piano.send_event_call_found = True   # hits were seen leaving the browser
            if pv.identifier and pv.identifier not in piano.site_ids:
                piano.site_ids.append(str(pv.identifier))

    findings: List[dict] = []
    findings += check_ga4(page)
    findings += check_gtm(page)
    findings += check_adobe(page)
    findings += check_piano(page)
    findings += check_clarity(page)
    findings += check_hotjar(page)
    findings += check_meta_pixel(page)
    findings += check_linkedin(page)
    findings += check_tiktok(page)
    findings += check_tagcommander(page)
    findings += check_data_layer(page, gtm_detected=gtm.detected)
    findings += check_duplicate_tags(page, _build_tracker_loads(
        ga4, gtm, adobe, piano, clarity, hotjar, meta_pixel, linkedin, tiktok,
    ))

    if runtime_result is not None:
        static_detected = {
            "ga4": ga4.detected, "gtm": gtm.detected, "adobe": adobe.detected,
            "piano": piano.detected, "clarity": clarity.detected, "hotjar": hotjar.detected,
            "meta_pixel": meta_pixel.detected, "linkedin": linkedin.detected, "tiktok": tiktok.detected,
        }
        findings += check_runtime_analytics(runtime_result, url, static_detected=static_detected)
        merge_static_detected_vendors(runtime_result, static_detected)
        findings = _drop_static_warnings_disproved_at_runtime(findings, runtime_result)

    score = score_analytics(findings)
    summary = build_analytics_summary(
        ga4_detection=ga4,
        gtm_detection=gtm,
        data_layer_detection=data_layer,
        meta_pixel_detection=meta_pixel,
        tiktok_detection=tiktok,
        other_detections={"adobe": adobe, "piano": piano, "clarity": clarity,
                           "hotjar": hotjar, "linkedin": linkedin, "tagcommander": tagcommander},
        score_result=score,
        runtime_result=runtime_result,
    )

    # Tools seen sending hits in the browser count as detected, even if no HTML names them.
    if runtime_result is not None and runtime_result.available:
        from analytics.analytics_score import TRACKER_DISPLAY_NAMES
        for key, vendor in (runtime_result.vendors or {}).items():
            if getattr(vendor, "captured_request_count", 0) <= 0 or key in summary.vendor_configs:
                continue
            summary.trackers_detected.append(TRACKER_DISPLAY_NAMES.get(key, getattr(vendor, "vendor_name", key)))
            summary.vendor_configs[key] = []
        # IDs seen in the browser fill in tags fired by a tag manager (no ID in the HTML).
        for key, ids in runtime_vendor_ids(runtime_result).items():
            if key not in summary.vendor_configs:
                continue
            merged = list(summary.vendor_configs.get(key) or [])
            for i in ids:
                if i and i not in merged:
                    merged.append(i)
            summary.vendor_configs[key] = merged

    # No analytics anywhere (code, browser, libraries): the most important finding, not a perfect score.
    if not summary.trackers_detected:
        consent_note = ""
        if runtime_result is not None and getattr(runtime_result, "available", False):
            consent_note = f" The live browser check ran (cookie banner: {runtime_result.consent_state or 'n/a'})."
        no_analytics = {
            "module": "analytics", "category": "presence", "severity": "critical",
            "title": "No analytics tracking found",
            "description": f"{url}: no analytics or tag-manager tag was found in the page code or in the live "
                           f"browser, including after accepting cookies.{consent_note} Visits, conversions and "
                           "campaigns on this site are not being measured.",
            "recommendation": "Install the organisation's analytics (e.g. via its tag manager) and gate it behind "
                              "the cookie banner, or confirm that measurement is intentionally absent.",
        }
        findings = findings + [no_analytics]
        score = score_analytics(findings)
        score.overall = 0
        summary.analytics_score = 0
    return AnalyticsAuditResult(findings=findings, score=score, summary=summary,
                                tags_injected_by_js=raw_detected == 0 and bool(summary.trackers_detected))


# Static "couldn't see X happen" warnings that the live browser check can prove wrong.
_RUNTIME_DISPROVABLE = {
    "Piano Analytics loaded without a detected sendEvent call": ("vendor_pv", "piano"),
    "Adobe Analytics loaded without a detected page-view call": ("vendor_pv", "adobe"),
    "GTM installed but no dataLayer activity found": ("global", "dataLayer"),
}


_RUNTIME_ID_PATTERNS = {
    "ga4": [re.compile(r"[?&]tid=(G-[A-Z0-9]+)", re.I), re.compile(r"gtag/js\?id=(G-[A-Z0-9]+)", re.I)],
    "gtm": [re.compile(r"gtm\.js\?id=(GTM-[A-Z0-9]+)", re.I)],
    "meta_pixel": [re.compile(r"facebook\.com/tr/?\?(?:.*&)?id=(\d+)", re.I), re.compile(r"/signals/config/(\d+)", re.I)],
    "linkedin": [re.compile(r"px\.ads\.linkedin\.com/.*[?&]pid=(\d+)", re.I)],
    "piano": [re.compile(r"[?&]s=(\d+)(?:&|$)", re.I)],
    "adobe": [re.compile(r"/b/ss/([^/]+)/", re.I)],
    "tagcommander": [re.compile(r"/tc_([A-Za-z0-9-]+)_\d+\.js", re.I)],
    "clarity": [re.compile(r"clarity\.ms/tag/([a-z0-9]+)", re.I)],
    "hotjar": [re.compile(r"hotjar-(\d+)\.js", re.I)],
    "tiktok": [re.compile(r"[?&]sdkid=([A-Z0-9]+)", re.I)],
}


def runtime_vendor_ids(runtime_result) -> dict:
    """Tool -> IDs seen in the browser (from the requests sent and the libraries loaded)."""
    out: dict = {}
    if runtime_result is None or not getattr(runtime_result, "available", False):
        return out

    def add(key, value):
        if value:
            lst = out.setdefault(key, [])
            if str(value) not in lst:
                lst.append(str(value))

    for key, vendor in (runtime_result.vendors or {}).items():
        add(key, getattr(vendor, "identifier", None))
        for url in getattr(vendor, "request_urls", None) or []:
            for rx in _RUNTIME_ID_PATTERNS.get(key, []):
                for m in rx.finditer(url):
                    add(key, m.group(1))
    g = runtime_result.page_globals or {}
    for tid in g.get("google_tag_ids") or []:
        if tid.upper().startswith("GTM-"):
            add("gtm", tid)
        elif tid.upper().startswith("G-"):
            add("ga4", tid)
    for pid in g.get("meta_pixel_ids") or []:
        add("meta_pixel", pid)
    for pid in g.get("linkedin_partner_ids") or []:
        add("linkedin", pid)
    for name in g.get("tagcommander_containers") or []:
        add("tagcommander", name)
    if g.get("piano_site"):
        add("piano", g.get("piano_site"))
    return out


def _drop_static_warnings_disproved_at_runtime(findings: List[dict], runtime_result) -> List[dict]:
    if runtime_result is None or not runtime_result.available:
        return findings
    vendors = runtime_result.vendors or {}
    globals_ = runtime_result.page_globals or {}

    def disproved(title: str) -> bool:
        rule = _RUNTIME_DISPROVABLE.get(title)
        if not rule:
            return False
        kind, key = rule
        if kind == "vendor_pv":
            v = vendors.get(key)
            return bool(v and getattr(v, "page_view_status", None) == "passed")
        return isinstance(globals_.get(key), int) and globals_[key] > 0

    return [f for f in findings if not disproved(f.get("title", ""))]


def _build_tracker_loads(ga4, gtm, adobe, piano, clarity, hotjar, meta_pixel, linkedin, tiktok) -> List[TrackerLoad]:
    return [
        TrackerLoad("ga4", "Google Analytics 4", ga4.measurement_ids,
                    # one loader per property is expected (dual tagging); only repeats of the same loader count
                    (max(1, len(ga4.measurement_ids)) + ga4.repeated_loader_count) if ga4.script_tag_count else 0),
        TrackerLoad("gtm", "Google Tag Manager", gtm.container_ids, gtm.script_tag_count),
        TrackerLoad("adobe", "Adobe Analytics", adobe.report_suites, 0),
        TrackerLoad("piano", "Piano Analytics", piano.site_ids, 0),
        TrackerLoad("clarity", "Microsoft Clarity", clarity.project_ids, clarity.script_tag_count),
        TrackerLoad("hotjar", "Hotjar", hotjar.site_ids, hotjar.script_tag_count),
        TrackerLoad("meta_pixel", "Meta Pixel", meta_pixel.pixel_ids, 1 if meta_pixel.loader_found else 0),
        TrackerLoad("linkedin", "LinkedIn Insight Tag", linkedin.partner_ids, 1 if linkedin.loader_found else 0),
        TrackerLoad("tiktok", "TikTok Pixel", tiktok.pixel_ids, 0),
    ]
