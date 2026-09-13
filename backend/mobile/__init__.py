"""
mobile/

A dedicated, granular mobile-UX check package — one file per concern —
for a "mobile" score that doesn't exist yet anywhere in the pipeline
(same situation ux/ describes: no `breakdown["mobile"] = ...`
placeholder currently sitting in services.audit_service.
run_audit_pipeline to replace, so wiring this in means adding a
"mobile" key to breakdown/EMPTY_BREAKDOWN rather than swapping one
out). Every check function returns findings in the same {module,
category, severity, title, description, recommendation} shape
services.audit_service / models.issue already persist, so it plugs
into Issue sync / report.html / history exactly like every other
module here.

    viewport      — <meta name="viewport"> presence and correctness
    responsive    — hard-coded fixed-width layout, missing @media
                    breakpoints (declared CSS only, see responsive.py)
    touch         — undersized tap targets, hover-only interactions
                    with no touch equivalent
    mobile_speed  — mobile-budget read of the same
                    performance.metrics.PerformanceMetrics the
                    performance/ package already computes (page
                    weight, LCP, render-blocking count, image count)
    mobile_score  — turns any list of these findings into a weighted
                    0-100 score with a per-category breakdown

Usage — wiring this into the real pipeline (crawler.crawler.Crawler
already produces a ParsedPage per page; performance.metrics.get_metrics
already produces a PerformanceMetrics for the audited URL):

    from mobile import run_page_checks, run_mobile_checks

    findings = run_page_checks(page)                    # viewport/responsive/touch
    findings += check_mobile_speed(metrics)              # from mobile.mobile_speed
    result = score_mobile(findings)

    # or, in one call given a homepage ParsedPage + its metrics:
    result = run_mobile_checks(page, metrics)
"""

from __future__ import annotations

from typing import List, Optional

from crawler.parser import ParsedPage
from performance.metrics import PerformanceMetrics

from mobile.mobile_score import MobileScoreResult, score_mobile
from mobile.mobile_speed import check_mobile_speed
from mobile.responsive import check_responsive
from mobile.touch import check_touch_targets
from mobile.viewport import check_viewport

__all__ = [
    "check_viewport",
    "check_responsive",
    "check_touch_targets",
    "check_mobile_speed",
    "score_mobile",
    "MobileScoreResult",
    "run_page_checks",
    "run_mobile_checks",
]


def run_page_checks(page: ParsedPage) -> List[dict]:
    """
    Every markup/declared-CSS-only mobile check for one already-fetched
    page: viewport, responsive layout, touch targets. Cheap and
    synchronous — safe to call once per page during a crawl, same as
    ux/accessibility/seo's page-level checks. Doesn't include
    mobile_speed, which needs a PerformanceMetrics rather than a bare
    ParsedPage — call check_mobile_speed separately (or use
    run_mobile_checks) once metrics are available.
    """
    findings: List[dict] = []
    findings += check_viewport(page)
    findings += check_responsive(page)
    findings += check_touch_targets(page)
    return findings


def run_mobile_checks(page: ParsedPage, metrics: Optional[PerformanceMetrics] = None) -> MobileScoreResult:
    """
    Convenience entry point: runs every page-level check plus (when
    metrics are supplied) mobile_speed, and scores the combined
    findings in one call. Pass metrics=None to score viewport/
    responsive/touch alone — "speed" simply stays at its default 100
    rather than being penalized for absent data.
    """
    findings = run_page_checks(page)
    if metrics is not None:
        findings += check_mobile_speed(metrics)
    return score_mobile(findings)
