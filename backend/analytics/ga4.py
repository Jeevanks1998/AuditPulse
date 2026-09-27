"""
analytics/ga4.py

Detects Google Analytics 4 (gtag.js) on a page: the loader script, any
gtag('config', 'G-XXXXXXXXXX') calls (however many — a page can legally
send data to more than one property), and — since it shares the same
gtag.js loader and the same 'config' call shape — legacy Universal
Analytics ('UA-XXXXXXX-X'), which stopped processing data in July 2023
and is now just dead weight if it's still on the page.

Reads crawler.parser.ParsedPage.soup directly: script src/inline text
isn't pulled into ParsedPage's normal fields, same rationale as
accessibility/contrast.py and accessibility/aria.py reading .soup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "ga4"

GA4_LOADER_RE = re.compile(r"googletagmanager\.com/gtag/js\?id=(G-[A-Z0-9]+)", re.IGNORECASE)
GA4_CONFIG_RE = re.compile(r"gtag\(\s*['\"]config['\"]\s*,\s*['\"](G-[A-Z0-9]+)['\"]", re.IGNORECASE)
GA4_ID_IN_SRC_RE = re.compile(r"\bG-[A-Z0-9]{6,}\b")

UA_LOADER_RE = re.compile(r"google-analytics\.com/analytics\.js", re.IGNORECASE)
UA_ID_RE = re.compile(r"\bUA-\d{4,}-\d+\b")


@dataclass
class GA4Detection:
    detected: bool = False
    measurement_ids: List[str] = field(default_factory=list)
    script_tag_count: int = 0  # how many gtag.js loader <script> tags were found
    config_call_count: int = 0  # how many gtag('config', ...) calls were found
    legacy_ua_ids: List[str] = field(default_factory=list)  # Universal Analytics IDs still present


def detect_ga4(page: ParsedPage) -> GA4Detection:
    """Scans this page's <script> tags (src + inline body) for GA4 and legacy UA signals."""
    result = GA4Detection()
    scripts = page.soup.find_all("script")

    measurement_ids: List[str] = []
    ua_ids: List[str] = []

    for tag in scripts:
        src = tag.get("src") or ""
        body = tag.string or tag.get_text() or ""

        loader_match = GA4_LOADER_RE.search(src)
        if loader_match:
            result.script_tag_count += 1
            measurement_ids.append(loader_match.group(1))
        elif GA4_ID_IN_SRC_RE.search(src):
            result.script_tag_count += 1
            measurement_ids += GA4_ID_IN_SRC_RE.findall(src)

        if UA_LOADER_RE.search(src):
            result.script_tag_count += 1

        for match in GA4_CONFIG_RE.finditer(body):
            result.config_call_count += 1
            measurement_ids.append(match.group(1))

        ua_ids += UA_ID_RE.findall(body) + UA_ID_RE.findall(src)

    # de-dupe while preserving first-seen order
    result.measurement_ids = list(dict.fromkeys(measurement_ids))
    result.legacy_ua_ids = list(dict.fromkeys(ua_ids))
    result.detected = bool(result.measurement_ids) or result.script_tag_count > 0

    return result


def check_ga4(page: ParsedPage) -> List[dict]:
    """Findings for GA4 configuration issues on this page. Absence of GA4 is not itself a finding."""
    detection = detect_ga4(page)
    findings: List[dict] = []

    if detection.legacy_ua_ids:
        shown = ", ".join(detection.legacy_ua_ids[:3])
        findings.append(_finding(
            "critical",
            "Legacy Universal Analytics tag still present",
            f"{page.url} still loads Universal Analytics ({shown}), which stopped "
            "processing hits in July 2023. Any traffic sent through this tag is "
            "silently discarded.",
            recommendation="Remove the Universal Analytics snippet. If this property "
                            "hasn't been migrated, set up GA4 in its place.",
        ))

    if detection.script_tag_count > 0 and not detection.measurement_ids:
        findings.append(_finding(
            "warning",
            "GA4 loader present with no resolvable measurement ID",
            f"{page.url} loads gtag.js but no G-XXXXXXXXXX measurement ID could be found "
            "in the loader URL or in a gtag('config', ...) call — the snippet is "
            "likely broken or incomplete.",
            recommendation="Confirm the gtag.js snippet includes a valid measurement ID "
                            "and a matching gtag('config', 'G-XXXXXXXXXX') call.",
        ))

    if detection.script_tag_count > 0 and detection.config_call_count == 0 and detection.measurement_ids \
            and detection.script_tag_count == len(detection.measurement_ids):
        # loader URL carried the ID but no explicit config() call was ever made
        findings.append(_finding(
            "info",
            "GA4 loaded without an explicit config() call",
            f"{page.url} loads gtag.js with a measurement ID in the URL but no "
            "gtag('config', ...) call was found — this is unusual outside of a "
            "Tag-Manager-managed setup.",
            recommendation="Verify GA4 is actually configured to send data, either via "
                            "an explicit config() call or through Google Tag Manager.",
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
