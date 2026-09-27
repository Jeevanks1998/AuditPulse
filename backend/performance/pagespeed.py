"""
performance/pagespeed.py

Owns the one outbound call this whole package makes: Google's PageSpeed
Insights (PSI) API. A single request returns two very different kinds
of data in one JSON blob:

  - `lighthouseResult` — a full Lighthouse *lab* run Google performs
    server-side against the URL right then. performance/lighthouse.py
    parses this half.
  - `loadingExperience` / `originLoadingExperience` — real-user *field*
    data from the Chrome UX Report (CrUX), i.e. what actual visitors to
    this URL (or origin) experienced over the last 28 days. This module
    owns that half directly, since it's a thin, PSI-specific shape that
    isn't "Lighthouse" at all.

Mirrors services.ai_service's shape: never raises on a missing key or a
failed call — every function here degrades to `None` / `[]` so a
missing GOOGLE_PAGESPEED_API_KEY (very likely in local/dev, see .env)
never takes the pipeline down. performance/metrics.py's fallback path
is what fills the gap when this returns nothing.
"""

from __future__ import annotations

from typing import List, Optional

import httpx

from config.logging import logger
from config.settings import settings

MODULE = "performance"
CATEGORY = "field_data"

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
REQUEST_TIMEOUT_SECONDS = 30.0  # PSI's own Lighthouse run can take a while

# CrUX reports CLS scaled by 100 (a percentile of 8 means an actual CLS of 0.08).
CLS_SCALE = 100

FIELD_METRIC_LABELS = {
    "LARGEST_CONTENTFUL_PAINT_MS": "Largest Contentful Paint (LCP)",
    "INTERACTION_TO_NEXT_PAINT": "Interaction to Next Paint (INP)",
    "FIRST_INPUT_DELAY_MS": "First Input Delay (FID)",
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": "Cumulative Layout Shift (CLS)",
    "FIRST_CONTENTFUL_PAINT_MS": "First Contentful Paint (FCP)",
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "Time to First Byte (TTFB)",
}

# Field-data metrics search engines use directly as Core Web Vitals ranking signals.
CORE_WEB_VITALS = {"LARGEST_CONTENTFUL_PAINT_MS", "INTERACTION_TO_NEXT_PAINT", "CUMULATIVE_LAYOUT_SHIFT_SCORE"}


async def fetch_pagespeed(
    client: httpx.AsyncClient,
    url: str,
    strategy: str = "mobile",
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> Optional[dict]:
    """
    Calls the PSI API for `url` and returns the raw JSON response, or
    None if no API key is configured or the call fails for any reason.
    `strategy` is "mobile" or "desktop" — PSI scores each separately,
    and mobile is the one that affects Google's mobile-first indexing.
    """
    if not settings.GOOGLE_PAGESPEED_API_KEY:
        logger.debug("performance.pagespeed: no GOOGLE_PAGESPEED_API_KEY configured, skipping PSI call")
        return None

    params = {
        "url": url,
        "key": settings.GOOGLE_PAGESPEED_API_KEY,
        "strategy": strategy,
        "category": "performance",
    }

    try:
        response = await client.get(PSI_ENDPOINT, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        logger.warning(f"performance.pagespeed: PSI request failed for {url}: {exc}")
        return None
    except ValueError as exc:  # response.json() failed
        logger.warning(f"performance.pagespeed: PSI returned non-JSON for {url}: {exc}")
        return None


def check_field_data(raw: Optional[dict]) -> List[dict]:
    """
    Findings from the real-user Core Web Vitals data in a PSI response.
    Falls back from per-URL `loadingExperience` to origin-wide
    `originLoadingExperience` when Google doesn't have enough traffic on
    the exact URL to report field data for it — common for anything but
    a site's homepage.
    """
    if not raw:
        return []

    experience = raw.get("loadingExperience") or raw.get("originLoadingExperience")
    if not experience or not experience.get("metrics"):
        return [_finding(
            "info",
            "No real-user performance data available",
            "Google doesn't have enough Chrome UX Report traffic for this URL or origin to "
            "report field data (actual visitor experience). This is normal for lower-traffic "
            "sites/pages — lab data from Lighthouse is the fallback signal.",
            recommendation=None,
        )]

    findings: List[dict] = []
    metrics = experience["metrics"]

    for metric_key in CORE_WEB_VITALS:
        metric = metrics.get(metric_key)
        if not metric:
            continue
        category = metric.get("category", "").upper()
        if category == "FAST":
            continue

        label = FIELD_METRIC_LABELS.get(metric_key, metric_key)
        value = _display_value(metric_key, metric.get("percentile"))
        severity = "critical" if category == "SLOW" else "warning"

        findings.append(_finding(
            severity,
            f"{label} needs improvement (real users)",
            f"Real Chrome users experience a 75th-percentile {label} of {value}, rated "
            f"\"{category.title()}\" by Google's Chrome UX Report. This is the number that "
            "affects Google's Core Web Vitals ranking signal, as distinct from a single "
            "Lighthouse lab run.",
            recommendation=_recommendation_for(metric_key),
        ))

    return findings


def _display_value(metric_key: str, percentile: Optional[float]) -> str:
    if percentile is None:
        return "unknown"
    if metric_key == "CUMULATIVE_LAYOUT_SHIFT_SCORE":
        return f"{percentile / CLS_SCALE:.2f}"
    if metric_key in ("LARGEST_CONTENTFUL_PAINT_MS", "FIRST_CONTENTFUL_PAINT_MS", "EXPERIMENTAL_TIME_TO_FIRST_BYTE"):
        return f"{percentile / 1000:.1f}s"
    return f"{percentile}ms"


def _recommendation_for(metric_key: str) -> Optional[str]:
    return {
        "LARGEST_CONTENTFUL_PAINT_MS": (
            "Speed up the largest above-the-fold element: optimize/preload the hero image or "
            "font, remove render-blocking resources, and improve server response time."
        ),
        "INTERACTION_TO_NEXT_PAINT": (
            "Reduce JavaScript execution time on interaction: break up long tasks, defer "
            "non-critical scripts, and minimize main-thread work."
        ),
        "FIRST_INPUT_DELAY_MS": (
            "Reduce main-thread blocking during page load so the first interaction responds "
            "faster; defer or split large JavaScript bundles."
        ),
        "CUMULATIVE_LAYOUT_SHIFT_SCORE": (
            "Reserve space for images/ads/embeds with explicit width and height, and avoid "
            "injecting content above existing content after load."
        ),
    }.get(metric_key)


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
