"""
analytics/duplicate_tags.py

Site-level(-ish) duplicate detection that sits on top of the other
analytics/* detectors rather than re-parsing the page itself. Each
tracker module (ga4, gtm, adobe, piano, clarity, hotjar, meta_pixel,
linkedin, tiktok) already knows how many times its loader appeared and
what ID(s) it found; this module just looks across that combined list
for two failure modes that are easy to introduce by accident (a
snippet pasted twice by two different people/plugins, or a migration
that added a new ID without removing the old one) and easy to miss
when looking at any single tracker in isolation:

  1. The same tracker's loader is included more than once -> double
     hit / double session-recording / inflated pageview counts.
  2. More than one distinct ID is configured for the same tracker on
     one page -> possibly intentional (multi-account setups exist) but
     worth a nudge to confirm.

Callers build the `TrackerLoad` list from each detect_*() result — see
analytics/__init__.py::run_page_checks for the wiring — rather than
this module importing and re-running every detector itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "duplicate_tags"


@dataclass
class TrackerLoad:
    """One tracker's aggregated detection result, in the shape duplicate-checking needs."""
    key: str  # short machine key, e.g. "ga4", matches the category used by that tracker's own findings
    display_name: str  # human-readable name, e.g. "Google Analytics 4"
    ids: List[str] = field(default_factory=list)
    load_count: int = 0  # number of loader/config occurrences found for this tracker


def check_duplicate_tags(page: ParsedPage, trackers: List[TrackerLoad]) -> List[dict]:
    """Findings for trackers loaded more than once, or configured with more than one ID, on this page."""
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
