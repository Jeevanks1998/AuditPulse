"""
analytics/analytics_score.py

Turns the flat finding lists every other analytics/* module returns
into a single weighted 0-100 score with a per-category breakdown — the
same shape Audit.breakdown["analytics"] / AuditStatsOut.breakdown
already carry for the other modules (see seo/seo_score.py,
accessibility/accessibility_score.py for the identical pattern).

Also exposes `build_analytics_summary`, which maps the individual
detect_*() results onto models.analytics.Analytics's columns
(trackers_detected, tag_manager_detected, gtm_container_id,
ga_measurement_id, data_layer_present, pageview_events_found,
custom_events_found, analytics_score) — this is what
services.audit_service._write_analytics_result should build from once
it's wired to the real detectors instead of its current
random.randint(...) placeholder.

Unlike SEO/accessibility, "no trackers found" is not a defect here —
plenty of legitimate sites run no analytics at all — so a category with
zero findings simply stays at 100 rather than being read as a failure.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:  # avoid importing analytics.runtime at module load time
    from analytics.runtime import AnalyticsRuntimeResult

MODULE = "analytics"

SEVERITY_PENALTY = {"critical": 30, "warning": 15, "info": 5}

# Must sum to 1.0. Categories not listed here (e.g. an unrecognized
# `category` value on a finding) are folded into "other" at a small
# default weight so nothing is silently dropped from the overall score.
CATEGORY_WEIGHTS: Dict[str, float] = {
    "ga4": 0.15,
    "gtm": 0.15,
    "adobe": 0.10,
    "piano": 0.05,
    "clarity": 0.05,
    "hotjar": 0.05,
    "meta_pixel": 0.10,
    "linkedin": 0.05,
    "tiktok": 0.05,
    "data_layer": 0.15,
    "duplicate_tags": 0.10,
}

_OTHER_CATEGORY = "other"
_OTHER_WEIGHT = 0.05

TRACKER_DISPLAY_NAMES: Dict[str, str] = {
    "ga4": "Google Analytics 4",
    "gtm": "Google Tag Manager",
    "adobe": "Adobe Analytics",
    "piano": "Piano Analytics",
    "clarity": "Microsoft Clarity",
    "hotjar": "Hotjar",
    "meta_pixel": "Meta Pixel",
    "linkedin": "LinkedIn Insight Tag",
    "tiktok": "TikTok Pixel",
}

# Which attribute on each vendor's Detection dataclass holds its list of
# actual detected IDs/configurations (ga4.GA4Detection.measurement_ids,
# adobe.AdobeDetection.report_suites, ...). Used by build_analytics_summary
# to build `vendor_configs` generically instead of one hard-coded field per
# vendor, so a vendor with more than one detected ID (e.g. two GA4
# properties on the same page) is represented as-is rather than truncated
# to a single value.
VENDOR_ID_ATTR: Dict[str, str] = {
    "ga4": "measurement_ids",
    "gtm": "container_ids",
    "adobe": "report_suites",
    "piano": "site_ids",
    "clarity": "project_ids",
    "hotjar": "site_ids",
    "meta_pixel": "pixel_ids",
    "linkedin": "partner_ids",
    "tiktok": "pixel_ids",
}


@dataclass
class AnalyticsScoreResult:
    overall: int
    breakdown: Dict[str, int] = field(default_factory=dict)
    counts_by_severity: Dict[str, int] = field(default_factory=dict)
    findings: List[dict] = field(default_factory=list)


def score_analytics(findings: List[dict]) -> AnalyticsScoreResult:
    """
    Scores a flat list of finding dicts (as returned by
    analytics.run_page_checks, or concatenated across an entire crawl)
    into an overall score plus per-category breakdown.
    """
    by_category: Dict[str, List[dict]] = {}
    for finding in findings:
        category = finding.get("category") or _OTHER_CATEGORY
        by_category.setdefault(category, []).append(finding)

    breakdown: Dict[str, int] = {}
    weight_total = 0.0
    weighted_sum = 0.0

    all_categories = set(CATEGORY_WEIGHTS) | set(by_category)
    for category in all_categories:
        weight = CATEGORY_WEIGHTS.get(category, _OTHER_WEIGHT)
        score = _score_category(by_category.get(category, []))
        breakdown[category] = score
        weight_total += weight
        weighted_sum += score * weight

    overall = round(weighted_sum / weight_total) if weight_total else 100

    counts_by_severity: Dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
    for finding in findings:
        severity = finding.get("severity", "info")
        counts_by_severity[severity] = counts_by_severity.get(severity, 0) + 1

    return AnalyticsScoreResult(
        overall=overall,
        breakdown=breakdown,
        counts_by_severity=counts_by_severity,
        findings=findings,
    )


def _score_category(category_findings: List[dict]) -> int:
    score = 100
    for finding in category_findings:
        score -= SEVERITY_PENALTY.get(finding.get("severity", "info"), SEVERITY_PENALTY["info"])
    return max(0, score)


@dataclass
class AnalyticsSummary:
    """Field-for-field match with models.analytics.Analytics, minus audit_id/id/created_at."""
    trackers_detected: List[str] = field(default_factory=list)
    tag_manager_detected: bool = False
    gtm_container_id: Optional[str] = None
    ga_measurement_id: Optional[str] = None
    data_layer_present: bool = False
    pageview_events_found: int = 0
    custom_events_found: int = 0
    analytics_score: int = 0

    # analytics.runtime.run_analytics_runtime's live Page View/Scroll/Click
    # verdicts. runtime_available: the Playwright pass executed at all.
    # runtime_tested: it captured at least one real vendor request, i.e.
    # this is genuine live evidence rather than an empty pass. Both are
    # the same boolean today (analytics/runtime.py has no separate
    # "ran but found nothing to click" leg the way consent/runtime.py
    # does) but kept as two fields for symmetry with ConsentSummary and
    # room for that distinction later.
    runtime_available: bool = False
    runtime_tested: bool = False
    runtime_result: Optional[dict] = None

    # Every detected vendor's actual configuration, keyed by vendor_key
    # (ga4, gtm, adobe, piano, clarity, hotjar, meta_pixel, linkedin,
    # tiktok) -> list of detected IDs. A vendor detected via a loader
    # script but with no ID extractable from the markup is present with
    # an empty list; an undetected vendor is simply absent from this
    # dict — never a placeholder/fallback ID. gtm_container_id and
    # ga_measurement_id above are kept for backward compatibility
    # (first detected value only); this is the full, multi-ID-aware
    # source of truth.
    vendor_configs: Dict[str, List[str]] = field(default_factory=dict)

    # Phase 2 full-site fields — see models.analytics.Analytics for the
    # column-level docs. Left at their defaults for a homepage-only audit;
    # populated by services.audit_service._run_analytics_checks_site.
    page_results: List[dict] = field(default_factory=list)
    site_coverage: Dict[str, int] = field(default_factory=dict)
    cross_page_findings: List[dict] = field(default_factory=list)


def build_analytics_summary(
    *,
    ga4_detection,
    gtm_detection,
    data_layer_detection,
    meta_pixel_detection=None,
    tiktok_detection=None,
    other_detections: Optional[Dict[str, object]] = None,
    score_result: Optional[AnalyticsScoreResult] = None,
    runtime_result: Optional["AnalyticsRuntimeResult"] = None,
) -> AnalyticsSummary:
    """
    Assembles an AnalyticsSummary ready to pass straight into
    models.analytics.Analytics(**vars(summary), audit_id=...). Takes
    the individual detect_*() results rather than the ParsedPage
    itself, since __init__.run_page_checks already computed all of
    them once and there's no reason to re-scan the page here.

    `other_detections` is an optional {category_key: detection} map for
    adobe/piano/clarity/hotjar/linkedin — anything with a truthy
    `.detected` contributes its display name to trackers_detected and
    its actual ID list (per VENDOR_ID_ATTR) to vendor_configs.
    """
    trackers: List[str] = []
    vendor_configs: Dict[str, List[str]] = {}

    all_detections: Dict[str, object] = {"ga4": ga4_detection, "gtm": gtm_detection}
    if meta_pixel_detection is not None:
        all_detections["meta_pixel"] = meta_pixel_detection
    if tiktok_detection is not None:
        all_detections["tiktok"] = tiktok_detection
    all_detections.update(other_detections or {})

    for key, detection in all_detections.items():
        if not getattr(detection, "detected", False):
            continue
        trackers.append(TRACKER_DISPLAY_NAMES.get(key, key))
        attr = VENDOR_ID_ATTR.get(key)
        # Detected-but-no-ID-extracted (e.g. a loader script with no
        # parseable account id) is represented as an empty list, never
        # omitted or backfilled with a placeholder — the vendor is
        # still real evidence, it just has no configuration value.
        vendor_configs[key] = list(getattr(detection, attr, []) or []) if attr else []

    pageview_events = data_layer_detection.pageview_events
    if meta_pixel_detection is not None and meta_pixel_detection.pageview_fired:
        pageview_events += 1
    if tiktok_detection is not None and tiktok_detection.page_call_found:
        pageview_events += 1

    runtime_available = bool(runtime_result and runtime_result.available)
    runtime_tested = bool(runtime_result and runtime_result.available and runtime_result.vendors)

    return AnalyticsSummary(
        trackers_detected=trackers,
        tag_manager_detected=gtm_detection.detected,
        gtm_container_id=gtm_detection.container_ids[0] if gtm_detection.container_ids else None,
        ga_measurement_id=ga4_detection.measurement_ids[0] if ga4_detection.measurement_ids else None,
        data_layer_present=data_layer_detection.present,
        pageview_events_found=pageview_events,
        custom_events_found=data_layer_detection.custom_events,
        analytics_score=score_result.overall if score_result else 100,
        runtime_available=runtime_available,
        runtime_tested=runtime_tested,
        runtime_result=dataclasses.asdict(runtime_result) if runtime_result else None,
        vendor_configs=vendor_configs,
    )


# ============================================================================
# Phase 2 — full-site: page-level results, cross-page consistency, site
# coverage, and a site-level score derived from actual page-level evidence
# (never the homepage score standing in for the whole site).
# ============================================================================

@dataclass
class PageAnalyticsResult:
    """One crawled page's analytics evidence — the unit services.audit_service
    aggregates across a full-site crawl. `findings` are this page's own
    (module=analytics) findings only; cross-page findings are computed
    separately by check_cross_page_consistency once every page is in."""

    url: str
    trackers_detected: List[str] = field(default_factory=list)
    vendor_configs: Dict[str, List[str]] = field(default_factory=dict)
    score: int = 100
    findings: List[dict] = field(default_factory=list)
    runtime_available: bool = False
    runtime_tested: bool = False
    runtime_result: Optional[dict] = None


def check_cross_page_consistency(pages: List[PageAnalyticsResult]) -> List[dict]:
    """
    Compares actual detected vendor_configs across every scanned page and
    flags real discrepancies — a tracker present on some pages and absent
    from others, or the same vendor configured with different IDs on
    different pages (different GA4 Measurement IDs, GTM Container IDs,
    Adobe Report Suites, Piano Site IDs, Clarity/Hotjar/Meta/LinkedIn/
    TikTok IDs). Only ever produced from >= 2 real crawled pages — a
    single-page audit has nothing to compare, so this returns [].
    """
    if len(pages) < 2:
        return []

    findings: List[dict] = []
    all_vendor_keys = set()
    for p in pages:
        all_vendor_keys.update(p.vendor_configs.keys())

    for vendor_key in sorted(all_vendor_keys):
        label = TRACKER_DISPLAY_NAMES.get(vendor_key, vendor_key)
        pages_with = [p for p in pages if vendor_key in p.vendor_configs]
        pages_without = [p for p in pages if vendor_key not in p.vendor_configs]

        if pages_with and pages_without:
            missing_urls = [p.url for p in pages_without]
            findings.append(_finding(
                "warning",
                f"{label} is missing from some pages",
                f"{label} was detected on {len(pages_with)} of {len(pages)} scanned pages but is "
                f"missing from: {', '.join(missing_urls[:10])}"
                + (f" and {len(missing_urls) - 10} more" if len(missing_urls) > 10 else "") + ".",
                f"Confirm whether {label} is meant to be installed site-wide; if so, add it to the "
                "pages where it's missing so reporting isn't undercounted for those pages.",
                category="cross_page_consistency",
                affected_urls=missing_urls,
            ))

        # Different actual IDs configured for the same vendor across pages.
        ids_to_pages: Dict[str, List[str]] = {}
        for p in pages_with:
            for vendor_id in p.vendor_configs.get(vendor_key) or []:
                ids_to_pages.setdefault(vendor_id, []).append(p.url)
        if len(ids_to_pages) > 1:
            detail = "; ".join(f"{vid} on {', '.join(urls[:5])}" for vid, urls in ids_to_pages.items())
            affected = sorted({url for urls in ids_to_pages.values() for url in urls})
            findings.append(_finding(
                "critical",
                f"Inconsistent {label} configuration across pages",
                f"More than one {label} ID/configuration was found across the scanned site: {detail}.",
                f"Standardize on a single {label} ID across the site — mixed IDs split traffic "
                "across separate properties/containers and undercount both.",
                category="cross_page_consistency",
                affected_urls=affected,
            ))

    return findings


def score_site_analytics(
    pages: List[PageAnalyticsResult], cross_page_findings: Optional[List[dict]] = None
) -> AnalyticsScoreResult:
    """
    Site-level score derived from every scanned page's actual findings
    plus real cross-page consistency findings — never just the homepage's
    score. A single-page ("homepage" depth) audit degrades to exactly
    score_analytics(homepage findings), which is the correct answer when
    there's only one real page of evidence to score.
    """
    combined: List[dict] = []
    for p in pages:
        combined += p.findings
    combined += cross_page_findings or []
    return score_analytics(combined)


def compute_site_coverage(
    pages: List[PageAnalyticsResult], cross_page_findings: Optional[List[dict]] = None
) -> Dict[str, int]:
    """
    Actual calculated coverage from the pages that were really crawled —
    every count here comes from `pages`/`cross_page_findings`, never a
    fixed or estimated number.
    """
    cross_page_findings = cross_page_findings or []
    inconsistent_urls = set()
    for f in cross_page_findings:
        if f.get("category") == "cross_page_consistency":
            inconsistent_urls.update(f.get("affected_urls") or [])

    return {
        "pages_scanned": len(pages),
        "pages_with_analytics": sum(1 for p in pages if p.trackers_detected),
        "pages_without_analytics": sum(1 for p in pages if not p.trackers_detected),
        "pages_with_runtime_failures": sum(
            1 for p in pages if p.runtime_available and any(
                f.get("category") == "runtime" and f.get("severity") == "critical" for f in p.findings
            )
        ),
        "pages_with_analytics_inconsistencies": sum(1 for p in pages if p.url in inconsistent_urls),
        "pages_with_findings": sum(1 for p in pages if p.findings),
    }


# ============================================================================
# Phase 2.5 — Consent + Analytics correlation. Connects consent.runtime's
# actual before/after-consent network capture (consent/runtime.py's
# ConsentRuntimeResult) with analytics' detected vendors, so a tracker that
# fires regardless of a Reject click (or that only appears after Accept) is
# flagged from real observed network requests — never assumed.
# ============================================================================

# consent/network.py's KNOWN_TRACKER_DOMAINS labels requests by a plain
# display name (domain-matched), not by analytics' vendor_key — this maps
# the overlap between the two so a detected analytics vendor can be matched
# against consent's captured request list. Vendors consent/network.py has
# no domain entry for (Adobe, Piano, LinkedIn) simply can't be correlated
# and are skipped, rather than guessed at.
_CONSENT_TRACKER_NAME_TO_VENDOR_KEY = {
    "google analytics": "ga4",
    "google tag manager": "gtm",
    "meta pixel": "meta_pixel",
    "meta": "meta_pixel",
    "tiktok pixel": "tiktok",
    "hotjar": "hotjar",
    "microsoft clarity": "clarity",
}


def check_consent_analytics_correlation(
    vendor_configs: Dict[str, List[str]],
    consent_runtime_result,
    page_url: str,
) -> List[dict]:
    """
    Compares actually-detected analytics vendors against
    consent.runtime.run_consent_runtime's real captured network requests
    before consent, after Reject, and after Accept. Only ever produces a
    finding when the runtime pass actually ran and actually captured a
    matching request — an unavailable/not-run consent runtime pass yields
    no findings here, never an assumed pass or fail.
    """
    findings: List[dict] = []
    if consent_runtime_result is None or not getattr(consent_runtime_result, "available", False):
        return findings
    if not vendor_configs:
        return findings

    after_reject = getattr(consent_runtime_result, "after_reject", None)
    if after_reject is not None and getattr(after_reject, "available", False):
        seen_vendors = set()
        for req in after_reject.tracker_requests:
            vendor_key = _CONSENT_TRACKER_NAME_TO_VENDOR_KEY.get((req.tracker_name or "").lower())
            if vendor_key and vendor_key in vendor_configs and vendor_key not in seen_vendors:
                seen_vendors.add(vendor_key)
                label = TRACKER_DISPLAY_NAMES.get(vendor_key, vendor_key)
                findings.append(_finding(
                    "critical",
                    f"{label} fires after consent was rejected",
                    f"{page_url}: a live browser session clicked Reject on the cookie banner, and "
                    f"{label} (detected in this page's markup) still sent a network request "
                    f"({req.url}) afterward.",
                    f"Gate {label}'s loader on the actual consent state — it should not fire "
                    "at all, or should stop firing, once a visitor rejects tracking.",
                    category="consent_correlation",
                    affected_urls=[page_url],
                ))

    before = getattr(consent_runtime_result, "before_consent", None)
    after_accept = getattr(consent_runtime_result, "after_accept", None)
    if (
        before is not None and getattr(before, "available", False)
        and after_accept is not None and getattr(after_accept, "available", False)
    ):
        before_vendor_keys = {
            _CONSENT_TRACKER_NAME_TO_VENDOR_KEY.get((r.tracker_name or "").lower())
            for r in before.tracker_requests
        }
        accept_vendor_keys = {
            _CONSENT_TRACKER_NAME_TO_VENDOR_KEY.get((r.tracker_name or "").lower())
            for r in after_accept.tracker_requests
        }
        # A detected vendor that never fires even once consent is
        # *accepted* is a real functional gap, not a compliance win —
        # worth surfacing distinctly from the Phase 1 "detected but never
        # fires at runtime" finding since this specifically confirms it
        # doesn't fire even with consent granted.
        for vendor_key in vendor_configs:
            if vendor_key in before_vendor_keys or vendor_key in accept_vendor_keys:
                continue
            if vendor_key not in _CONSENT_TRACKER_NAME_TO_VENDOR_KEY.values():
                continue  # not one consent/network.py can observe at all
            label = TRACKER_DISPLAY_NAMES.get(vendor_key, vendor_key)
            findings.append(_finding(
                "warning",
                f"{label} did not fire even after consent was accepted",
                f"{page_url}: a live browser session clicked Accept on the cookie banner, but no "
                f"{label} network request was observed before or after — {label} is detected in "
                "markup but appears non-functional regardless of consent state.",
                f"Confirm {label}'s trigger condition isn't blocked by something other than "
                "consent (a JS error, a misconfigured tag, an ad blocker in the test environment).",
                category="consent_correlation",
                affected_urls=[page_url],
            ))

    return findings


def _finding(
    severity: str, title: str, description: str, recommendation: str,
    category: str = MODULE, affected_urls: Optional[List[str]] = None,
) -> dict:
    finding = {
        "module": MODULE,
        "category": category,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
    if affected_urls:
        # Extra, additive key — every other module's findings already
        # persist fine without it (models.issue only reads the six
        # standard keys), so this is purely additional evidence for the
        # report's cross-page section, not a shape change other code
        # needs to handle.
        finding["affected_urls"] = affected_urls
    return finding
