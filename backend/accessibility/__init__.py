"""
accessibility/

A dedicated, granular accessibility-check package — one file per
concern — that supersedes the handful of accessibility rules currently
inlined in crawler/extractor.py::_build_findings and the
`breakdown["accessibility"] = random.randint(75, 96)` placeholder in
services.audit_service.run_audit_pipeline. Every check function returns
findings in the same {module, category, severity, title, description,
recommendation} shape services.audit_service / models.issue already
persist, so nothing downstream (Issue sync, report.html, history) needs
to change to consume them.

Two kinds of checks live here, same split as seo/:

Page-level (sync, take a crawler.parser.ParsedPage — cheap, safe to run
on every crawled page):
    contrast, aria, keyboard, labels, heading

Live-render (async, need a rendered-DOM run against the actual URL —
one call each per URL, not per page fetch, since both are
network/subprocess calls of their own):
    axe   — Google PageSpeed Insights, category=accessibility (axe-core
             rules, via Lighthouse; needs GOOGLE_PAGESPEED_API_KEY)
    pa11y — local pa11y CLI, HTML CodeSniffer WCAG2AA ruleset (optional;
             degrades to [] if the `pa11y` binary isn't installed)

`accessibility_score.py` turns any list of these findings into a
weighted 0-100 score with a per-category breakdown, the same shape as
Audit.breakdown / AuditStatsOut.breakdown already use for
"accessibility".

Usage — wiring this into the real pipeline (crawler.crawler.Crawler
already produces a ParsedPage per page; this replaces the accessibility
portion of extract_signals' findings, it doesn't replace the whole
crawl):

    from accessibility import run_page_checks, run_live_checks, score_accessibility

    page_findings = run_page_checks(page)
    live_findings, lighthouse_score = await run_live_checks(client, page.url)
    result = score_accessibility(page_findings + live_findings, lighthouse_score)
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import httpx

from crawler.parser import ParsedPage

from accessibility.accessibility_score import AccessibilityScoreResult, score_accessibility
from accessibility.aria import check_aria
from accessibility.axe import AxeAuditResult, check_axe_audits, fetch_axe_audit
from accessibility.contrast import check_contrast
from accessibility.heading import check_heading_structure
from accessibility.keyboard import check_keyboard
from accessibility.labels import check_labels
from accessibility.pa11y import pa11y_available, run_pa11y

__all__ = [
    "check_contrast",
    "check_aria",
    "check_keyboard",
    "check_labels",
    "check_heading_structure",
    "fetch_axe_audit",
    "check_axe_audits",
    "AxeAuditResult",
    "run_pa11y",
    "pa11y_available",
    "score_accessibility",
    "AccessibilityScoreResult",
    "run_page_checks",
    "run_live_checks",
    "run_accessibility_checks",
    "AccessibilityAuditResult",
]


def run_page_checks(page: ParsedPage) -> List[dict]:
    """
    Every check that only needs one already-fetched, already-parsed
    page. Cheap and synchronous — safe to call once per page during a
    crawl.
    """
    findings: List[dict] = []
    findings += check_contrast(page)
    findings += check_aria(page)
    findings += check_keyboard(page)
    findings += check_labels(page)
    findings += check_heading_structure(page)
    return findings


async def run_live_checks(
    client: httpx.AsyncClient,
    url: str,
    include_pa11y: bool = True,
) -> Tuple[List[dict], Optional[int], Optional[dict]]:
    """
    Everything that needs its own rendered-DOM run against the live
    URL: a PSI/axe-core pass and (optionally) a local pa11y pass.
    Call this once per URL, not once per page-parse. Returns
    (findings, lighthouse_accessibility_score, raw_psi_response) — the
    score half feeds accessibility_score.score_accessibility's
    Lighthouse blend, and the raw response is kept around in case a
    caller (e.g. report_service) wants detail beyond the flat findings.
    """
    axe_result = await fetch_axe_audit(client, url)
    findings: List[dict] = list(axe_result.findings)

    if include_pa11y and pa11y_available():
        findings += await run_pa11y(url)

    return findings, axe_result.category_score, axe_result.raw


class AccessibilityAuditResult:
    """Lightweight container mirroring performance.PerformanceAuditResult's shape."""

    def __init__(self, findings: List[dict], score: AccessibilityScoreResult, raw_axe: Optional[dict]):
        self.findings = findings
        self.score = score
        self.raw_axe = raw_axe


async def run_accessibility_checks(
    client: httpx.AsyncClient,
    page: ParsedPage,
    include_pa11y: bool = True,
) -> AccessibilityAuditResult:
    """
    Convenience one-call entry point for a single page: runs every
    page-level check plus both live-render checks for page.url, then
    scores the combined findings. Prefer run_page_checks/run_live_checks
    separately when a caller wants to batch the live calls differently
    from the (much cheaper) page-level ones across a multi-page crawl.
    """
    page_findings = run_page_checks(page)
    live_findings, lighthouse_score, raw_axe = await run_live_checks(
        client, page.url, include_pa11y=include_pa11y
    )

    all_findings = page_findings + live_findings
    score = score_accessibility(all_findings, lighthouse_accessibility_score=lighthouse_score)

    return AccessibilityAuditResult(findings=all_findings, score=score, raw_axe=raw_axe)
