"""
performance/metrics.py

A single PerformanceMetrics shape regardless of where the numbers came
from: Lighthouse lab data (performance.lighthouse.parse_lab_metrics)
when a PSI response is available, or a direct-measurement fallback when
it isn't — no GOOGLE_PAGESPEED_API_KEY configured, or the PSI call
failed (see performance.pagespeed.fetch_pagespeed, which already
degrades to None rather than raising).

The fallback never tries to *simulate* Lighthouse — it can't render a
page or execute JavaScript. It measures what a plain HTTP client
honestly can: time to first byte, total transfer time, HTML document
weight, and resource counts parsed out of the markup. That's enough to
drive performance.optimization's heuristic checks and give
performance.performance_score something to work with even with zero
external dependencies.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import httpx

from config.logging import logger
from crawler.parser import ParsedPage, parse_html
from performance.lighthouse import LabMetrics, parse_lab_metrics

REQUEST_TIMEOUT_SECONDS = 15.0


@dataclass
class PerformanceMetrics:
    """
    Normalized metrics used by optimization.py / performance_score.py.
    Fields carried over from Lighthouse lab data keep their native units
    (milliseconds, bytes); fallback-only fields (`resource_counts`,
    `page: ParsedPage`) are None when the metrics came from Lighthouse
    instead, since PSI doesn't hand back the page's raw markup.
    """

    source: str  # "lighthouse" | "fallback"

    performance_score: Optional[int] = None
    ttfb_ms: Optional[float] = None
    total_load_ms: Optional[float] = None
    largest_contentful_paint_ms: Optional[float] = None
    cumulative_layout_shift: Optional[float] = None
    total_byte_weight_bytes: Optional[float] = None

    resource_counts: Dict[str, int] = field(default_factory=dict)
    response_headers: Dict[str, str] = field(default_factory=dict)
    page: Optional[ParsedPage] = None


def metrics_from_lighthouse(lab: LabMetrics) -> PerformanceMetrics:
    """Reshapes performance.lighthouse.LabMetrics into the common PerformanceMetrics."""
    return PerformanceMetrics(
        source="lighthouse",
        performance_score=lab.performance_score,
        ttfb_ms=lab.server_response_time_ms,
        total_load_ms=lab.speed_index_ms,
        largest_contentful_paint_ms=lab.largest_contentful_paint_ms,
        cumulative_layout_shift=lab.cumulative_layout_shift,
        total_byte_weight_bytes=lab.total_byte_weight_bytes,
    )


async def measure_fallback_metrics(
    client: httpx.AsyncClient, url: str, timeout: float = REQUEST_TIMEOUT_SECONDS
) -> Optional[PerformanceMetrics]:
    """
    Direct measurement when no PSI/Lighthouse data is available: streams
    the response to time TTFB (headers received) separately from total
    transfer time, then parses the HTML for resource counts. Returns
    None if the request fails outright — callers should treat that the
    same as "no metrics available" rather than a zero score.
    """
    started = time.monotonic()
    try:
        async with client.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            ttfb_ms = (time.monotonic() - started) * 1000
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
            total_load_ms = (time.monotonic() - started) * 1000
    except httpx.HTTPError as exc:
        logger.warning(f"performance.metrics: fallback measurement failed for {url}: {exc}")
        return None

    html = bytes(body).decode(response.encoding or "utf-8", errors="ignore")
    page = parse_html(url, html)
    resource_counts = _count_resources(page)

    return PerformanceMetrics(
        source="fallback",
        ttfb_ms=round(ttfb_ms, 1),
        total_load_ms=round(total_load_ms, 1),
        total_byte_weight_bytes=len(body),
        resource_counts=resource_counts,
        response_headers=dict(response.headers),
        page=page,
    )


async def get_metrics(
    client: httpx.AsyncClient, url: str, raw_pagespeed: Optional[dict] = None
) -> Optional[PerformanceMetrics]:
    """
    Convenience entrypoint: prefers Lighthouse lab data already fetched
    into `raw_pagespeed` (see performance.pagespeed.fetch_pagespeed),
    falling back to a direct measurement when that's unavailable.
    """
    lab = parse_lab_metrics(raw_pagespeed)
    if lab is not None:
        return metrics_from_lighthouse(lab)
    return await measure_fallback_metrics(client, url)


def _count_resources(page: ParsedPage) -> Dict[str, int]:
    soup = page.soup
    scripts = soup.find_all("script", src=True)
    stylesheets = [
        tag for tag in soup.find_all("link")
        if any((r or "").lower() == "stylesheet" for r in _rel_list(tag))
    ]
    fonts = [
        tag for tag in soup.find_all("link")
        if any((r or "").lower() == "preload" for r in _rel_list(tag)) and tag.get("as") == "font"
    ]

    return {
        "scripts": len(scripts),
        "stylesheets": len(stylesheets),
        "images": len(page.image_tags),
        "fonts": len(fonts),
        "total": len(scripts) + len(stylesheets) + len(page.image_tags) + len(fonts),
    }


def _rel_list(tag) -> list:
    rel = tag.get("rel") or []
    return [rel] if isinstance(rel, str) else rel
