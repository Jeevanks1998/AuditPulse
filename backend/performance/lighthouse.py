"""
performance/lighthouse.py

Parses the `lighthouseResult` half of a PSI response (see
performance/pagespeed.py for the field-data half and the actual HTTP
call) into structured lab metrics and audit-level findings. This is lab
data — a single simulated run against the URL at request time — as
opposed to pagespeed.py's real-user field data; the two frequently
disagree, which is normal and worth surfacing rather than picking one.

Every audit id/threshold below is a well-known, stable part of the
Lighthouse performance category (id names come straight from Google's
audit catalog), so this stays correct even as Lighthouse's internal
scoring model changes version to version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

MODULE = "performance"
CATEGORY = "lab_data"

# Lighthouse's own 0-1 audit score. Below this, the audit is surfaced as
# a finding; the exact cutoff mirrors what Lighthouse's own report UI
# highlights as "opportunities" / failing audits (score < 0.9 = orange
# or red in Lighthouse's report).
FAILING_AUDIT_THRESHOLD = 0.9

# Core render/paint timing audits — reported unconditionally as metrics,
# not gated on a pass/fail score, since the timing itself is the finding.
TIMING_AUDIT_IDS = (
    "first-contentful-paint",
    "largest-contentful-paint",
    "speed-index",
    "total-blocking-time",
    "cumulative-layout-shift",
    "server-response-time",
)

# "Opportunity" audits — Lighthouse audits that carry an estimated time
# savings when the underlying issue is fixed.
OPPORTUNITY_AUDIT_IDS = (
    "render-blocking-resources",
    "unminified-css",
    "unminified-javascript",
    "unused-css-rules",
    "unused-javascript",
    "modern-image-formats",
    "offscreen-images",
    "uses-text-compression",
    "uses-responsive-images",
    "efficient-animated-content",
    "uses-long-cache-ttl",
    "total-byte-weight",
    "dom-size",
)

_RECOMMENDATIONS = {
    "server-response-time": "Speed up the initial server response — cache rendered pages, "
                             "use a CDN, or optimize slow backend queries.",
    "render-blocking-resources": "Defer or inline critical CSS/JS and load the rest "
                                  "asynchronously so the browser can start painting sooner.",
    "unminified-css": "Minify CSS files to remove whitespace and comments before serving them.",
    "unminified-javascript": "Minify JavaScript files as part of the build/deploy process.",
    "unused-css-rules": "Remove or split unused CSS (e.g. per-route bundles) so pages don't "
                         "download styles they never apply.",
    "unused-javascript": "Code-split and lazy-load JavaScript so pages don't download code "
                          "they don't run.",
    "modern-image-formats": "Serve images as WebP or AVIF instead of JPEG/PNG where supported.",
    "offscreen-images": "Lazy-load images below the fold with loading=\"lazy\".",
    "uses-text-compression": "Enable gzip or Brotli compression for text assets (HTML/CSS/JS) "
                              "at the server or CDN.",
    "uses-responsive-images": "Serve appropriately sized images via srcset instead of one "
                               "large image scaled down by CSS.",
    "efficient-animated-content": "Replace animated GIFs with video formats (e.g. MP4/WebM), "
                                   "which are dramatically smaller for the same animation.",
    "uses-long-cache-ttl": "Set long max-age Cache-Control headers on static assets so repeat "
                            "visits don't re-download them.",
    "total-byte-weight": "Reduce total page weight — compress images, remove unused code, and "
                          "avoid loading assets the page doesn't need.",
    "dom-size": "Simplify the DOM — very large or deeply nested DOM trees slow down style and "
                "layout calculations.",
}


@dataclass
class LabMetrics:
    """Numeric lab-run values pulled straight off known Lighthouse audits, in their native units."""

    performance_score: Optional[int] = None  # 0-100 (Lighthouse's own category score * 100)
    first_contentful_paint_ms: Optional[float] = None
    largest_contentful_paint_ms: Optional[float] = None
    speed_index_ms: Optional[float] = None
    total_blocking_time_ms: Optional[float] = None
    cumulative_layout_shift: Optional[float] = None
    server_response_time_ms: Optional[float] = None
    total_byte_weight_bytes: Optional[float] = None
    extra: Dict[str, float] = field(default_factory=dict)


def parse_lab_metrics(raw: Optional[dict]) -> Optional[LabMetrics]:
    """Extracts LabMetrics from a raw PSI response. Returns None if lab data isn't present."""
    lighthouse = (raw or {}).get("lighthouseResult")
    if not lighthouse:
        return None

    audits = lighthouse.get("audits", {})
    category_score = (lighthouse.get("categories", {}).get("performance") or {}).get("score")

    def numeric(audit_id: str) -> Optional[float]:
        audit = audits.get(audit_id) or {}
        return audit.get("numericValue")

    return LabMetrics(
        performance_score=round(category_score * 100) if category_score is not None else None,
        first_contentful_paint_ms=numeric("first-contentful-paint"),
        largest_contentful_paint_ms=numeric("largest-contentful-paint"),
        speed_index_ms=numeric("speed-index"),
        total_blocking_time_ms=numeric("total-blocking-time"),
        cumulative_layout_shift=numeric("cumulative-layout-shift"),
        server_response_time_ms=numeric("server-response-time"),
        total_byte_weight_bytes=numeric("total-byte-weight"),
    )


def check_lighthouse(raw: Optional[dict]) -> List[dict]:
    """
    Findings from the lab-run Lighthouse audits in a PSI response: slow
    timing metrics plus any "opportunity" audit that scored below
    FAILING_AUDIT_THRESHOLD. Returns [] if no lab data is present —
    callers should treat that as "unavailable", not "everything's fine".
    """
    lighthouse = (raw or {}).get("lighthouseResult")
    if not lighthouse:
        return []

    audits = lighthouse.get("audits", {})
    findings: List[dict] = []

    for audit_id in TIMING_AUDIT_IDS:
        findings += _check_timing_audit(audit_id, audits.get(audit_id))

    for audit_id in OPPORTUNITY_AUDIT_IDS:
        findings += _check_opportunity_audit(audit_id, audits.get(audit_id))

    return findings


def _check_timing_audit(audit_id: str, audit: Optional[dict]) -> List[dict]:
    if not audit:
        return []
    score = audit.get("score")
    if score is None or score >= FAILING_AUDIT_THRESHOLD:
        return []

    severity = "critical" if score < 0.5 else "warning"
    display_value = audit.get("displayValue") or "n/a"
    title = audit.get("title", audit_id)
    description = audit.get("description", "").split(" [Learn")[0]  # trim Lighthouse's markdown link suffix

    return [_finding(
        severity,
        f"{title}: {display_value}",
        description or f"Lighthouse scored the \"{title}\" metric at {round(score * 100)}/100.",
        recommendation=_RECOMMENDATIONS.get(audit_id),
    )]


def _check_opportunity_audit(audit_id: str, audit: Optional[dict]) -> List[dict]:
    if not audit:
        return []
    score = audit.get("score")
    if score is None or score >= FAILING_AUDIT_THRESHOLD:
        return []

    severity = "critical" if score < 0.5 else "warning" if score < 0.75 else "info"
    title = audit.get("title", audit_id)
    display_value = audit.get("displayValue")
    savings_note = f" (potential savings: {display_value})" if display_value else ""

    return [_finding(
        severity,
        title,
        f"Lighthouse flagged \"{title}\"{savings_note}. Score: {round(score * 100)}/100.",
        recommendation=_RECOMMENDATIONS.get(audit_id),
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
