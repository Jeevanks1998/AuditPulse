"""
analytics/piano.py

Detects Piano Analytics — the rebrand of AT Internet's measurement
suite. Sites migrated at different times, so both the current loader
domain (tag.aticdn.net serving the "pa" library) and the legacy
xiti.com collection domain can still turn up in the wild, alongside the
`pa.sendEvent(...)` call the current SDK uses to send hits.

Reads crawler.parser.ParsedPage.soup directly, same rationale as the
other analytics/* modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "piano"

LOADER_SRC_RE = re.compile(r"tag\.aticdn\.net|piano-analytics", re.IGNORECASE)
LEGACY_COLLECTION_RE = re.compile(r"[\w.-]+\.xiti\.com", re.IGNORECASE)
SEND_EVENT_RE = re.compile(r"\bpa\.sendEvent\s*\(", re.IGNORECASE)
SITE_ID_RE = re.compile(r"site\s*[:=]\s*['\"]?(\d+)['\"]?", re.IGNORECASE)


@dataclass
class PianoDetection:
    detected: bool = False
    uses_current_sdk: bool = False  # tag.aticdn.net / piano-analytics loader
    uses_legacy_collection: bool = False  # bare xiti.com hits, no current loader
    send_event_call_found: bool = False
    site_ids: List[str] = field(default_factory=list)


def detect_piano(page: ParsedPage) -> PianoDetection:
    """Scans this page's <script> tags for Piano Analytics / AT Internet signals."""
    result = PianoDetection()
    site_ids: List[str] = []

    for tag in page.soup.find_all("script"):
        src = tag.get("src") or ""
        body = tag.string or tag.get_text() or ""

        if LOADER_SRC_RE.search(src) or LOADER_SRC_RE.search(body):
            result.uses_current_sdk = True
        if LEGACY_COLLECTION_RE.search(src) or LEGACY_COLLECTION_RE.search(body):
            result.uses_legacy_collection = True
        if SEND_EVENT_RE.search(body):
            result.send_event_call_found = True

        site_ids += SITE_ID_RE.findall(body)

    result.site_ids = list(dict.fromkeys(site_ids)) if (result.uses_current_sdk or result.uses_legacy_collection) else []
    result.detected = result.uses_current_sdk or result.uses_legacy_collection
    return result


def check_piano(page: ParsedPage) -> List[dict]:
    """Findings for Piano Analytics configuration issues. Absence of Piano tagging is not itself a finding."""
    detection = detect_piano(page)
    findings: List[dict] = []

    if not detection.detected:
        return findings

    if detection.uses_legacy_collection and not detection.uses_current_sdk:
        findings.append(_finding(
            "info",
            "Legacy AT Internet collection domain in use",
            f"{page.url} sends hits to an xiti.com collection endpoint without the "
            "current Piano Analytics (tag.aticdn.net) loader present — likely an "
            "older integration that predates the AT Internet -> Piano rebrand.",
            recommendation="Confirm this is intentional; consider migrating to the "
                            "current Piano Analytics SDK if it isn't.",
        ))

    if detection.uses_current_sdk and not detection.send_event_call_found:
        findings.append(_finding(
            "warning",
            "Piano Analytics loaded without a detected sendEvent call",
            f"{page.url} loads the Piano Analytics SDK but no pa.sendEvent(...) call "
            "was found in the page's inline scripts, so this page may not be "
            "sending any hits.",
            recommendation="Confirm a page-view or event call actually fires on this page.",
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
