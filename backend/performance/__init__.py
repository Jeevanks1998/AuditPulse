"""
performance/

A dedicated performance-check package — one file per concern — that
supersedes the `breakdown["performance"] = random.randint(70, 97)`
placeholder in services.audit_service.run_audit_pipeline.

Two data sources feed it, and both are optional independently:

  - Google PageSpeed Insights (PSI), via pagespeed.fetch_pagespeed, if
    GOOGLE_PAGESPEED_API_KEY is configured (see config.settings /
    .env). One API call returns both real-user field data
    (pagespeed.py) and a fresh Lighthouse lab run (lighthouse.py).
  - A direct-measurement fallback (metrics.measure_fallback_metrics)
    that needs no API key at all — it streams the page itself to time
    TTFB/total load and parses the markup for resource counts, headers,
    and structural issues (optimization.py).

Usage — wiring this into the real pipeline in place of the placeholder:

    from performance import run_performance_checks

    result = await run_performance_checks(client, audit.url)
    breakdown["performance"] = result.score.overall
    findings += result.findings
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import httpx

from performance.lighthouse import LabMetrics, check_lighthouse, parse_lab_metrics
from performance.metrics import PerformanceMetrics, get_metrics
from performance.optimization import check_optimizations
from performance.pagespeed import check_field_data, fetch_pagespeed
from performance.performance_score import PerformanceScoreResult, score_performance

__all__ = [
    "check_lighthouse",
    "parse_lab_metrics",
    "LabMetrics",
    "get_metrics",
    "PerformanceMetrics",
    "check_optimizations",
    "fetch_pagespeed",
    "check_field_data",
    "score_performance",
    "PerformanceScoreResult",
    "run_performance_checks",
    "PerformanceAuditResult",
]


@dataclass
class PerformanceAuditResult:
    findings: List[dict]
    metrics: Optional[PerformanceMetrics]
    score: PerformanceScoreResult
    raw_pagespeed: Optional[dict]  # kept around in case a caller (e.g. report_service) wants raw detail


async def run_performance_checks(
    client: httpx.AsyncClient, url: str, strategy: str = "mobile"
) -> PerformanceAuditResult:
    """
    Runs every performance check for one URL: attempts a PSI/Lighthouse
    call first, always runs the header/markup optimization checks
    against whatever metrics ended up available (fallback-measured or
    not — see performance.optimization, which no-ops cleanly on
    Lighthouse-sourced metrics), and returns one aggregated result ready
    to merge into an audit's findings + breakdown.
    """
    raw = await fetch_pagespeed(client, url, strategy=strategy)

    findings: List[dict] = []
    findings += check_field_data(raw)
    findings += check_lighthouse(raw)

    metrics = await get_metrics(client, url, raw_pagespeed=raw)
    if metrics is not None:
        findings += check_optimizations(metrics)

    lab = parse_lab_metrics(raw)
    lighthouse_score = lab.performance_score if lab else None

    score = score_performance(findings, lighthouse_score=lighthouse_score)

    return PerformanceAuditResult(findings=findings, metrics=metrics, score=score, raw_pagespeed=raw)
