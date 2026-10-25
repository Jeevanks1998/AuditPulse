"""
Finds tracking tags loaded twice (double-counted page views) or with more
than one ID for the same tool (may be intended, worth checking).
Works on the other detectors' results; doesn't re-scan the page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "duplicate_tags"


@dataclass
class TrackerLoad:
    """One tool's detection summary for the duplicate check."""
    key: str  # e.g. "ga4"
    display_name: str  # e.g. "Google Analytics 4"
    ids: List[str] = field(default_factory=list)
    load_count: int = 0  # times the tag's loader or config was found


def check_duplicate_tags(page: ParsedPage, trackers: List[TrackerLoad]) -> List[dict]:
    """Findings for tools loaded more than once or with several IDs on this page."""
    findings: List[dict] = []

    for tracker in trackers:
        if not tracker.ids and tracker.load_count <= 1:
            continue

        if tracker.load_count > 1:
            findings.append(_finding(
                "warning",
                f"{tracker.display_name} loaded more than once",
                f"{page.url} includes {tracker.display_name}'s loader/config "
                f"{tracker.load_count} times. This typically means the same hit, "
                "recording, or pageview gets counted more than once per visit.",
                recommendation=f"Keep a single {tracker.display_name} install on this page — "
                                "check for a snippet pasted both directly and through a "
                                "tag manager, or added by more than one plugin/template.",
            ))

        distinct_ids = list(dict.fromkeys(tracker.ids))
        if len(distinct_ids) > 1:
            shown = ", ".join(distinct_ids[:5])
            findings.append(_finding(
                "info",
                f"Multiple {tracker.display_name} IDs on one page",
                f"{page.url} configures more than one {tracker.display_name} ID: {shown}.",
                recommendation="Confirm every ID listed is intentional (e.g. a shared "
                                "container plus a site-specific one) rather than a leftover "
                                "from a migration or copy-paste.",
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
