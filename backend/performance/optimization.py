"""
performance/optimization.py

Actionable optimization findings that don't depend on Lighthouse or a
PSI API key — just the response headers and markup already gathered by
performance.metrics.measure_fallback_metrics. This is what still runs
in local/dev with GOOGLE_PAGESPEED_API_KEY unset (see .env), and it
still adds value even when Lighthouse data *is* available, since it
looks directly at response headers Lighthouse's audits summarize but
don't always name explicitly (e.g. exact Cache-Control values).

Every check here takes a performance.metrics.PerformanceMetrics with
`source == "fallback"` — the ones with `page` and `response_headers`
populated. Called with a "lighthouse"-sourced metrics object, every
check simply finds nothing to inspect and returns [] rather than
raising, so callers never need to branch on `metrics.source` first.
"""

from __future__ import annotations

from typing import List, Optional

from performance.metrics import PerformanceMetrics

MODULE = "performance"
CATEGORY = "optimization"

LARGE_HTML_BYTES = 100 * 1024        # 100KB of raw HTML markup alone is a lot
HIGH_RESOURCE_COUNT = 80             # scripts + stylesheets + images + fonts
RENDER_BLOCKING_HEAD_LIMIT = 6       # sync <script>/<link rel=stylesheet> tags in <head>
INLINE_ASSET_MIN_BYTES = 2000        # ignore tiny inline snippets when checking minification


def check_optimizations(metrics: PerformanceMetrics) -> List[dict]:
    """Findings derived from response headers and markup on a fallback-measured page."""
    if metrics.source != "fallback" or metrics.page is None:
        return []

    findings: List[dict] = []
    findings += _check_compression(metrics)
    findings += _check_caching(metrics)
    findings += _check_render_blocking(metrics)
    findings += _check_resource_count(metrics)
    findings += _check_page_weight(metrics)
    findings += _check_inline_minification(metrics)
    findings += _check_responsive_images(metrics)
    return findings


def _check_compression(metrics: PerformanceMetrics) -> List[dict]:
    encoding = (metrics.response_headers.get("content-encoding") or "").lower()
    if encoding in ("gzip", "br", "zstd"):
        return []
    return [_finding(
        "warning",
        "Text compression not enabled",
        "The response has no Content-Encoding header (gzip/brotli), so HTML is sent "
        "uncompressed over the wire.",
        recommendation="Enable gzip or Brotli compression at the server or CDN for "
                        "text-based responses (HTML, CSS, JS, JSON).",
    )]


def _check_caching(metrics: PerformanceMetrics) -> List[dict]:
    cache_control = (metrics.response_headers.get("cache-control") or "").lower()
    if not cache_control:
        return [_finding(
            "info",
            "No Cache-Control header on the document",
            "The page response has no Cache-Control header at all, leaving caching "
            "behavior entirely up to browser defaults and any intermediary proxies.",
            recommendation="Set an explicit Cache-Control header — even \"no-cache\" for "
                            "frequently-changing pages is better than none, and static "
                            "assets should carry a long max-age.",
        )]
    if "no-store" in cache_control:
        return [_finding(
            "info",
            "Document is marked no-store",
            f"Cache-Control is \"{cache_control}\", preventing any caching, including by "
            "the browser's back/forward cache. Fine for sensitive pages, wasteful for "
            "ordinary content pages.",
            recommendation="Use no-store only where required (e.g. authenticated/sensitive "
                            "pages); allow caching for ordinary public content.",
        )]
    return []


def _check_render_blocking(metrics: PerformanceMetrics) -> List[dict]:
    soup = metrics.page.soup
    head = soup.find("head")
    if head is None:
        return []

    blocking_scripts = [
        tag for tag in head.find_all("script", src=True)
        if tag.get("async") is None and tag.get("defer") is None and tag.get("type") != "module"
    ]
    blocking_styles = [
        tag for tag in head.find_all("link")
        if any((r or "").lower() == "stylesheet" for r in _rel_list(tag)) and tag.get("media") not in ("print",)
    ]
    total_blocking = len(blocking_scripts) + len(blocking_styles)

    if total_blocking <= RENDER_BLOCKING_HEAD_LIMIT:
        return []

    return [_finding(
        "warning",
        "Many render-blocking resources in <head>",
        f"{total_blocking} synchronous scripts/stylesheets ({len(blocking_scripts)} script(s), "
        f"{len(blocking_styles)} stylesheet(s)) load in <head> before the browser can start "
        "painting the page.",
        recommendation="Add async/defer to non-critical scripts, inline small critical CSS, "
                        "and load the rest of the stylesheet asynchronously.",
    )]


def _check_resource_count(metrics: PerformanceMetrics) -> List[dict]:
    total = metrics.resource_counts.get("total", 0)
    if total <= HIGH_RESOURCE_COUNT:
        return []
    return [_finding(
        "info",
        "High number of page resources",
        f"The page references {total} scripts/stylesheets/images/fonts. Each is a separate "
        "request, and a high count adds up even on a fast connection.",
        recommendation="Bundle/combine assets where practical, lazy-load below-the-fold "
                        "images, and audit third-party scripts for ones that can be removed.",
    )]


def _check_page_weight(metrics: PerformanceMetrics) -> List[dict]:
    weight = metrics.total_byte_weight_bytes or 0
    if weight <= LARGE_HTML_BYTES:
        return []
    return [_finding(
        "info",
        "Large HTML document",
        f"The initial HTML document is {weight / 1024:.0f}KB. This is the document alone, "
        "before any linked CSS/JS/images even start downloading.",
        recommendation="Reduce inline scripts/styles and repeated markup; consider "
                        "server-side pagination for very long pages.",
    )]


def _check_inline_minification(metrics: PerformanceMetrics) -> List[dict]:
    soup = metrics.page.soup
    inline_blocks = soup.find_all("script", src=False) + soup.find_all("style")
    unminified = 0

    for tag in inline_blocks:
        text = tag.string or tag.get_text() or ""
        if len(text) < INLINE_ASSET_MIN_BYTES:
            continue
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        avg_line_len = len(text) / len(lines)
        # Hand-authored/unminified code wraps often; minifiers emit one dense line.
        if avg_line_len < 120:
            unminified += 1

    if not unminified:
        return []
    return [_finding(
        "info",
        "Inline scripts/styles may be unminified",
        f"{unminified} inline <script>/<style> block(s) over {INLINE_ASSET_MIN_BYTES} bytes "
        "are formatted like unminified source (short, indented lines) rather than a build "
        "output.",
        recommendation="Run inline scripts/styles through a minifier as part of the build, "
                        "or move them to external minified files.",
    )]


def _check_responsive_images(metrics: PerformanceMetrics) -> List[dict]:
    images = metrics.page.image_tags or []
    if not images:
        return []

    missing_dimensions = sum(1 for img in images if not (img.get("width") and img.get("height")))
    if missing_dimensions == 0:
        return []

    return [_finding(
        "info",
        "Images missing explicit dimensions",
        f"{missing_dimensions} of {len(images)} images have no width/height attributes, so "
        "the browser can't reserve space for them before they load — a common cause of "
        "layout shift.",
        recommendation="Add width and height attributes (or aspect-ratio in CSS) to every "
                        "<img> so the browser reserves the right amount of space.",
    )]


def _rel_list(tag) -> list:
    rel = tag.get("rel") or []
    return [rel] if isinstance(rel, str) else rel


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
