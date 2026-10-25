"""
Accessibility checks, one file per topic. Findings use the same shape as
every other module.

Page checks (fast, run on each page): contrast, aria, keyboard, labels, heading.
Live checks (one per URL): axe (via Google PageSpeed, needs an API key) and
pa11y (only if the pa11y CLI is installed).
accessibility_score.py turns the findings into a 0-100 score.
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
    """Checks that only need the already-parsed page. Fast; run once per page."""
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
    """Checks that load the live URL: PageSpeed/axe and, if installed, pa11y.
    Returns (findings, lighthouse_score, raw_psi_response).
    """
    axe_result = await fetch_axe_audit(client, url)
    findings: List[dict] = list(axe_result.findings)

    if include_pa11y and pa11y_available():
        findings += await run_pa11y(url)

    return findings, axe_result.category_score, axe_result.raw


class AccessibilityAuditResult:
    """Result container: findings, score and breakdown."""

    def __init__(self, findings: List[dict], score: AccessibilityScoreResult, raw_axe: Optional[dict]):
        self.findings = findings
        self.score = score
        self.raw_axe = raw_axe


async def run_accessibility_checks(
    client: httpx.AsyncClient,
    page: ParsedPage,
    include_pa11y: bool = True,
) -> AccessibilityAuditResult:
    """Runs all checks for one page and scores them."""
    page_findings = run_page_checks(page)
    live_findings, lighthouse_score, raw_axe = await run_live_checks(
        client, page.url, include_pa11y=include_pa11y
    )

    all_findings = page_findings + live_findings
    score = score_accessibility(all_findings, lighthouse_accessibility_score=lighthouse_score)

    return AccessibilityAuditResult(findings=all_findings, score=score, raw_axe=raw_axe)
