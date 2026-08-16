"""
analytics/clarity.py

Detects Microsoft Clarity, the free session-recording/heatmap tool.
Its install snippet is a small inline script that defines a `clarity`
function and appends a loader from www.clarity.ms/tag/<project-id>, so
both the project ID and the "is it actually wired up" signal live in
the same inline block.

Reads crawler.parser.ParsedPage.soup directly, same rationale as the
other analytics/* modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "clarity"

CLARITY_SRC_RE = re.compile(r"clarity\.ms/tag/([a-z0-9]+)", re.IGNORECASE)
CLARITY_FUNC_RE = re.compile(r"\bclarity\s*\(\s*['\"]", re.IGNORECASE)


@dataclass
class ClarityDetection:
    detected: bool = False
    project_ids: List[str] = field(default_factory=list)
    script_tag_count: int = 0
    api_call_found: bool = False  # clarity('set'/'identify'/'consent', ...) usage beyond the base snippet


def detect_clarity(page: ParsedPage) -> ClarityDetection:
    """Scans this page's <script> tags for Microsoft Clarity signals."""
    result = ClarityDetection()
    project_ids: List[str] = []

    for tag in page.soup.find_all("script"):
        src = tag.get("src") or ""
        body = tag.string or tag.get_text() or ""

        src_match = CLARITY_SRC_RE.search(src)
        body_match = CLARITY_SRC_RE.search(body)
        if src_match or body_match:
            result.script_tag_count += 1
            project_ids.append((src_match or body_match).group(1))

        if CLARITY_FUNC_RE.search(body):
            result.api_call_found = True

    result.project_ids = list(dict.fromkeys(project_ids))
    result.detected = bool(result.project_ids) or result.script_tag_count > 0
    return result


def check_clarity(page: ParsedPage) -> List[dict]:
    """Findings for Microsoft Clarity issues. Absence of Clarity is not itself a finding."""
    detection = detect_clarity(page)
    findings: List[dict] = []

    if len(detection.project_ids) > 1:
        shown = ", ".join(detection.project_ids[:5])
        findings.append(_finding(
            "info",
            "Multiple Clarity project IDs detected",
            f"{page.url} loads more than one Clarity project: {shown}. Session "
            "recordings will be split across projects unless this is intentional.",
            recommendation="Confirm every project ID listed is meant to be here.",
        ))

    if detection.script_tag_count > 1:
        findings.append(_finding(
            "warning",
            "Clarity snippet loaded more than once",
            f"{page.url} includes the Clarity loader {detection.script_tag_count} times, "
            "which means session data may be recorded (and counted) more than once "
            "per visit.",
            recommendation="Keep a single Clarity install snippet per page.",
        ))

    return findings


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
