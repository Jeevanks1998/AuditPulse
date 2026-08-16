"""
analytics/linkedin.py

Detects the LinkedIn Insight Tag: the inline snippet that sets
`_linkedin_partner_id` and loads insight.min.js from snap.licdn.com,
plus the recommended <noscript><img src=".../px.ads.linkedin.com/
collect..."> fallback for browsers without JavaScript — same
script+noscript pairing pattern as GTM and the Meta Pixel.

Reads crawler.parser.ParsedPage.soup directly, same rationale as the
other analytics/* modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "linkedin"

LOADER_SRC_RE = re.compile(r"snap\.licdn\.com/li\.lms-analytics/insight\.min\.js", re.IGNORECASE)
PARTNER_ID_RE = re.compile(r"_linkedin_partner_id\s*=\s*['\"](\d+)['\"]", re.IGNORECASE)
NOSCRIPT_FALLBACK_RE = re.compile(r"px\.ads\.linkedin\.com/collect", re.IGNORECASE)


@dataclass
class LinkedInDetection:
    detected: bool = False
    partner_ids: List[str] = field(default_factory=list)
    loader_found: bool = False
    has_noscript_fallback: bool = False


def detect_linkedin(page: ParsedPage) -> LinkedInDetection:
    """Scans this page's <script>/<noscript> tags for LinkedIn Insight Tag signals."""
    result = LinkedInDetection()
    partner_ids: List[str] = []

    for tag in page.soup.find_all("script"):
        src = tag.get("src") or ""
        body = tag.string or tag.get_text() or ""

        if LOADER_SRC_RE.search(src):
            result.loader_found = True

        partner_ids += PARTNER_ID_RE.findall(body)

    for tag in page.soup.find_all("noscript"):
        if NOSCRIPT_FALLBACK_RE.search(str(tag)):
            result.has_noscript_fallback = True

    result.partner_ids = list(dict.fromkeys(partner_ids))
    result.detected = result.loader_found or bool(result.partner_ids)
    return result


def check_linkedin(page: ParsedPage) -> List[dict]:
    """Findings for LinkedIn Insight Tag issues. Absence of the tag is not itself a finding."""
    detection = detect_linkedin(page)
    findings: List[dict] = []

    if not detection.detected:
        return findings

    if detection.partner_ids and not detection.loader_found:
        findings.append(_finding(
            "warning",
            "LinkedIn partner ID set without the Insight Tag loader",
            f"{page.url} sets _linkedin_partner_id but no insight.min.js loader "
            "script was found — the tag is configured but never actually loads.",
            recommendation="Confirm the full LinkedIn Insight Tag snippet, including "
                            "the insight.min.js loader, is present.",
        ))

    if detection.detected and not detection.has_noscript_fallback:
        findings.append(_finding(
            "info",
            "LinkedIn Insight Tag noscript fallback is missing",
            f"{page.url} loads the LinkedIn Insight Tag but has no matching "
            "<noscript><img src=\".../px.ads.linkedin.com/collect...\"> fallback for "
            "visitors without JavaScript.",
            recommendation="Add the noscript <img> fallback from LinkedIn's Insight "
                            "Tag base code alongside the JS snippet.",
        ))

    if len(detection.partner_ids) > 1:
        shown = ", ".join(detection.partner_ids[:5])
        findings.append(_finding(
            "info",
            "Multiple LinkedIn partner IDs detected",
            f"{page.url} references more than one LinkedIn partner ID: {shown}.",
            recommendation="Confirm every partner ID listed is meant to be here.",
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
