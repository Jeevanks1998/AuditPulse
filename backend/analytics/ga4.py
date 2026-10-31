"""
Detects Google Analytics 4 (gtag.js): the loader and every
gtag('config', 'G-...') call. Also finds old Universal Analytics IDs (UA-...),
which stopped working in July 2023.
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
    script_tag_count: int = 0  # gtag.js loader tags found
    repeated_loader_count: int = 0  # extra copies of the same gtag.js loader (same address)
    config_call_count: int = 0  # gtag('config', ...) calls found
    legacy_ua_ids: List[str] = field(default_factory=list)  # old Universal Analytics IDs still on the page


def detect_ga4(page: ParsedPage) -> GA4Detection:
    """Looks for GA4 and old UA in the page's scripts."""
    result = GA4Detection()
    scripts = page.soup.find_all("script")

    measurement_ids: List[str] = []
    ua_ids: List[str] = []
    loader_srcs: List[str] = []

    for tag in scripts:
        src = tag.get("src") or ""
        body = tag.string or tag.get_text() or ""

        loader_match = GA4_LOADER_RE.search(src)
        if loader_match:
            result.script_tag_count += 1
            measurement_ids.append(loader_match.group(1))
            loader_srcs.append(src.split("#")[0].strip().lower())
        elif GA4_ID_IN_SRC_RE.search(src):
            result.script_tag_count += 1
            measurement_ids += GA4_ID_IN_SRC_RE.findall(src)
            loader_srcs.append(src.split("#")[0].strip().lower())

        if UA_LOADER_RE.search(src):
            result.script_tag_count += 1

        for match in GA4_CONFIG_RE.finditer(body):
            result.config_call_count += 1
            measurement_ids.append(match.group(1))

        ua_ids += UA_ID_RE.findall(body) + UA_ID_RE.findall(src)

    # The same loader address twice is a real duplicate; one loader per property is not.
    result.repeated_loader_count = len(loader_srcs) - len(set(loader_srcs))
    # remove duplicates, keep order
    result.measurement_ids = list(dict.fromkeys(measurement_ids))
    result.legacy_ua_ids = list(dict.fromkeys(ua_ids))
    result.detected = bool(result.measurement_ids) or result.script_tag_count > 0

    return result


def check_ga4(page: ParsedPage) -> List[dict]:
    """Findings for GA4 problems. No GA4 at all is not a finding."""
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
        # the loader URL has the ID but config() is never called
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
