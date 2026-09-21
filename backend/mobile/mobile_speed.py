"""
mobile/mobile_speed.py

Mobile-specific read of the same performance.metrics.PerformanceMetrics
that performance/optimization.py and performance/performance_score.py
already consume — deliberately not a second network fetch. A page can
pass a generic desktop performance budget and still be slow on a
throttled mobile connection, so the thresholds here (page-weight
budget, render-blocking resource count, image count) are tighter than
performance/optimization.py's, modeling a mid-tier phone on a
throttled 4G connection rather than a broadband desktop.

Works with either metrics.source ("lighthouse" or "fallback"): the
byte-weight and LCP checks use fields both sources populate
(total_byte_weight_bytes, largest_contentful_paint_ms), while the
markup-derived checks (render-blocking count, image count) need
metrics.page and so quietly return [] for "lighthouse"-sourced
metrics, the same degrade-gracefully pattern performance/optimization.
py uses.
"""

from __future__ import annotations

from typing import List, Optional

from performance.metrics import PerformanceMetrics

MODULE = "mobile"
CATEGORY = "speed"

# A widely-cited "feels fast on mobile" budget for total transferred
# page weight; well above what a 100KB-HTML desktop budget would flag.
MOBILE_PAGE_WEIGHT_BUDGET_BYTES = 1.6 * 1024 * 1024
MOBILE_PAGE_WEIGHT_HARD_LIMIT_BYTES = 3 * 1024 * 1024

# On throttled mobile, LCP guidance is the same absolute number Core
# Web Vitals uses (2.5s "good"), but it's far easier to blow past on a
# slow connection, so it's worth checking here as well as in
# performance/performance_score.py's own LCP handling.
MOBILE_LCP_GOOD_MS = 2500
MOBILE_LCP_POOR_MS = 4000

RENDER_BLOCKING_MOBILE_LIMIT = 4
HIGH_IMAGE_COUNT_MOBILE = 15


def check_mobile_speed(metrics: PerformanceMetrics) -> List[dict]:
    """Findings for mobile-budget page weight, LCP, render-blocking resources, and image count."""
    findings: List[dict] = []
    findings += _check_page_weight(metrics)
    findings += _check_lcp(metrics)
    findings += _check_render_blocking(metrics)
    findings += _check_image_count(metrics)
    return findings


def _check_page_weight(metrics: PerformanceMetrics) -> List[dict]:
    weight = metrics.total_byte_weight_bytes
    if weight is None:
        return []

    if weight >= MOBILE_PAGE_WEIGHT_HARD_LIMIT_BYTES:
        severity = "critical"
    elif weight >= MOBILE_PAGE_WEIGHT_BUDGET_BYTES:
        severity = "warning"
    else:
        return []

    weight_mb = weight / (1024 * 1024)
    budget_mb = MOBILE_PAGE_WEIGHT_BUDGET_BYTES / (1024 * 1024)
    return [_finding(
        severity,
        "Page weight exceeds a mobile budget",
        f"The page transfers roughly {weight_mb:.1f}MB, over the ~{budget_mb:.1f}MB budget "
        "commonly used as a threshold for feeling fast on a throttled mobile connection. "
        "The same weight is far less noticeable on broadband.",
        recommendation="Compress and lazy-load images, defer non-critical JS/CSS, and audit "
                        "third-party scripts — these are usually the largest contributors to "
                        "page weight.",
    )]


def _check_lcp(metrics: PerformanceMetrics) -> List[dict]:
    lcp = metrics.largest_contentful_paint_ms
    if lcp is None:
        return []

    if lcp >= MOBILE_LCP_POOR_MS:
        severity = "critical"
    elif lcp >= MOBILE_LCP_GOOD_MS:
        severity = "warning"
    else:
        return []

    return [_finding(
        severity,
        "Largest Contentful Paint is slow",
        f"LCP is {lcp:.0f}ms. Core Web Vitals treats {MOBILE_LCP_GOOD_MS}ms as the \"good\" "
        f"threshold and {MOBILE_LCP_POOR_MS}ms+ as \"poor\" — this gap is generally most "
        "visible on mobile connections, where bandwidth and latency are the bottleneck "
        "rather than raw CPU.",
        recommendation="Prioritize the largest above-the-fold image or text block: preload "
                        "it, serve it at an appropriately sized resolution, and avoid "
                        "render-blocking resources ahead of it in the document.",
    )]


def _check_render_blocking(metrics: PerformanceMetrics) -> List[dict]:
    if metrics.source != "fallback" or metrics.page is None:
        return []

    count = metrics.resource_counts.get("scripts", 0) + metrics.resource_counts.get("stylesheets", 0)
    if count <= RENDER_BLOCKING_MOBILE_LIMIT:
        return []

    return [_finding(
        "warning",
        "Many render-blocking resources for a mobile connection",
        f"The page references {count} script/stylesheet tags that can block first render. "
        "On a fast desktop connection this is often invisible; on a throttled mobile "
        "connection each blocking request adds a full round-trip before the page can paint.",
        recommendation="Defer or async non-critical scripts, inline small critical CSS, and "
                        "combine or lazy-load the rest so the mobile round-trip cost is paid "
                        "by fewer requests.",
    )]


def _check_image_count(metrics: PerformanceMetrics) -> List[dict]:
    if metrics.source != "fallback" or metrics.page is None:
        return []

    count = metrics.resource_counts.get("images", 0)
    if count <= HIGH_IMAGE_COUNT_MOBILE:
        return []

    return [_finding(
        "info",
        "High image count on a single page",
        f"The page loads {count} <img> tags. On mobile, each additional image competes for "
        "limited bandwidth on a connection that's often both slower and metered compared to "
        "desktop broadband.",
        recommendation="Lazy-load below-the-fold images (see images/lazyload.py) and "
                        "consider pagination or a \"load more\" pattern for long image-heavy "
                        "pages.",
    )]


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
