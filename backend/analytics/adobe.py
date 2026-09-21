"""
analytics/adobe.py

Detects Adobe Analytics / Experience Cloud tagging in either of its two
common forms: the modern Adobe Experience Platform Launch (now "Tags")
loader served from assets.adobedtm.com, or the legacy hand-rolled
AppMeasurement.js + s_code.js pair. Both ultimately talk to Adobe's
collection endpoints (typically *.omtrdc.net or a first-party CNAME),
and both expose an `s` object with an `s_account`/`s.account` report
suite ID and `s.t()` (page view) / `s.tl()` (link/event tracking) calls.

Reads crawler.parser.ParsedPage.soup directly, same rationale as the
other analytics/* modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "adobe"

LAUNCH_SRC_RE = re.compile(r"assets\.adobedtm\.com", re.IGNORECASE)
APPMEASUREMENT_SRC_RE = re.compile(r"appmeasurement\.js", re.IGNORECASE)
COLLECTION_ENDPOINT_RE = re.compile(r"[\w.-]+\.omtrdc\.net", re.IGNORECASE)
SATELLITE_RE = re.compile(r"_satellite\s*\.")
REPORT_SUITE_RE = re.compile(r"s(?:_account|\.account)\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
PAGEVIEW_CALL_RE = re.compile(r"\bs\.t\s*\(")
LINK_TRACK_CALL_RE = re.compile(r"\bs\.tl\s*\(")


@dataclass
class AdobeDetection:
    detected: bool = False
    uses_launch: bool = False  # assets.adobedtm.com (Experience Platform Launch/Tags)
    uses_legacy_appmeasurement: bool = False  # hand-rolled AppMeasurement.js/s_code.js
    report_suites: List[str] = field(default_factory=list)
    pageview_call_found: bool = False


def detect_adobe(page: ParsedPage) -> AdobeDetection:
    """Scans this page's <script> tags for Adobe Analytics / Launch signals."""
    result = AdobeDetection()
    report_suites: List[str] = []

    for tag in page.soup.find_all("script"):
        src = tag.get("src") or ""
        body = tag.string or tag.get_text() or ""

        if LAUNCH_SRC_RE.search(src):
            result.uses_launch = True
        if APPMEASUREMENT_SRC_RE.search(src):
            result.uses_legacy_appmeasurement = True
        if COLLECTION_ENDPOINT_RE.search(src) or COLLECTION_ENDPOINT_RE.search(body):
            result.uses_legacy_appmeasurement = result.uses_legacy_appmeasurement or not result.uses_launch
        if SATELLITE_RE.search(body):
            result.uses_launch = True

        report_suites += REPORT_SUITE_RE.findall(body)
        if PAGEVIEW_CALL_RE.search(body):
            result.pageview_call_found = True
        if LINK_TRACK_CALL_RE.search(body) and not result.pageview_call_found:
            result.pageview_call_found = False  # link tracking alone doesn't imply a page view fired

    result.report_suites = list(dict.fromkeys(report_suites))
    result.detected = result.uses_launch or result.uses_legacy_appmeasurement or bool(result.report_suites)
    return result


def check_adobe(page: ParsedPage) -> List[dict]:
    """Findings for Adobe Analytics configuration issues. Absence of Adobe tagging is not itself a finding."""
    detection = detect_adobe(page)
    findings: List[dict] = []

    if not detection.detected:
        return findings

    if detection.uses_legacy_appmeasurement and not detection.uses_launch:
        findings.append(_finding(
            "info",
            "Legacy AppMeasurement.js in use without Launch",
            f"{page.url} loads Adobe's AppMeasurement.js directly rather than through "
            "Experience Platform Launch (Tags). This still works, but it means every "
            "future tagging change requires a code deploy instead of a Launch publish.",
            recommendation="Consider migrating to Adobe Experience Platform Launch/Tags "
                            "for tag-management benefits (versioning, rules, no-deploy changes).",
        ))

    if (detection.uses_launch or detection.uses_legacy_appmeasurement) and not detection.pageview_call_found:
        findings.append(_finding(
            "warning",
            "Adobe Analytics loaded without a detected page-view call",
            f"{page.url} loads Adobe Analytics tagging but no s.t() page-view call "
            "(or _satellite rule that would trigger one) was found in the page's "
            "inline scripts. This page may not be sending page-view data.",
            recommendation="Confirm a page-view beacon actually fires on this page, "
                            "e.g. via Launch's Core \"Page Bottom\" rule or an explicit s.t() call.",
        ))

    if not detection.report_suites:
        findings.append(_finding(
            "info",
            "No Adobe report suite ID found",
            f"Adobe Analytics tagging was detected on {page.url} but no report suite "
            "ID (s_account / s.account) could be resolved from static markup — it may "
            "be set dynamically via Launch data elements, which this check can't see.",
            recommendation=None,
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
