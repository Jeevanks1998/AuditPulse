"""
analytics/hotjar.py

Detects Hotjar (heatmaps/session recordings/surveys). The classic
install snippet defines a window._hjSettings object with `hjid` (site
ID) and `hjsv` (snippet version) before loading
static.hotjar.com/c/hotjar-<hjid>.js — both the site ID and an easy
"is this an old snippet" signal live in that one inline block.

Reads crawler.parser.ParsedPage.soup directly, same rationale as the
other analytics/* modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "hotjar"

HOTJAR_SRC_RE = re.compile(r"static\.hotjar\.com/c/hotjar-(\d+)", re.IGNORECASE)
HJID_RE = re.compile(r"hjid\s*:\s*(\d+)", re.IGNORECASE)
HJSV_RE = re.compile(r"hjsv\s*:\s*(\d+)", re.IGNORECASE)

# Snippet versions below this are several years old; Hotjar's current
# snippet has been on v6 for a long time, so anything under this is worth flagging.
MIN_CURRENT_HJSV = 6


@dataclass
class HotjarDetection:
    detected: bool = False
    site_ids: List[str] = field(default_factory=list)
    snippet_version: Optional[int] = None
    script_tag_count: int = 0


def detect_hotjar(page: ParsedPage) -> HotjarDetection:
    """Scans this page's <script> tags for Hotjar signals."""
    result = HotjarDetection()
    site_ids: List[str] = []
    versions: List[int] = []

    for tag in page.soup.find_all("script"):
        src = tag.get("src") or ""
        body = tag.string or tag.get_text() or ""

        src_match = HOTJAR_SRC_RE.search(src)
        if src_match:
            result.script_tag_count += 1
            site_ids.append(src_match.group(1))

        site_ids += HJID_RE.findall(body)
        versions += [int(v) for v in HJSV_RE.findall(body)]

    result.site_ids = list(dict.fromkeys(site_ids))
    result.snippet_version = min(versions) if versions else None
    result.detected = bool(result.site_ids) or result.script_tag_count > 0
    return result


def check_hotjar(page: ParsedPage) -> List[dict]:
    """Findings for Hotjar configuration issues. Absence of Hotjar is not itself a finding."""
    detection = detect_hotjar(page)
    findings: List[dict] = []

    if not detection.detected:
        return findings

    if detection.snippet_version is not None and detection.snippet_version < MIN_CURRENT_HJSV:
        findings.append(_finding(
            "info",
            "Hotjar snippet looks outdated",
            f"{page.url} uses a Hotjar snippet reporting version {detection.snippet_version}, "
            f"older than Hotjar's current snippet (v{MIN_CURRENT_HJSV}+).",
            recommendation="Regenerate the install snippet from Hotjar's site settings "
                            "to pick up the current tracking code.",
        ))

    if len(detection.site_ids) > 1:
        shown = ", ".join(detection.site_ids[:5])
        findings.append(_finding(
            "info",
            "Multiple Hotjar site IDs detected",
            f"{page.url} references more than one Hotjar site ID: {shown}.",
            recommendation="Confirm every site ID listed is meant to be here.",
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
