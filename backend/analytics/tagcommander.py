"""
analytics/tagcommander.py

Detects TagCommander / Commanders Act (now part of Commanders Act's
"TC" product line). The loader script is served from
cdn.tagcommander.com (or a client-specific CNAME) as
`tc_<container>_<version>.js`, and sites typically also expose a
`tc_vars` object (declared before the loader) and/or a global `tC`
event API used for manual tag firing.

Reads crawler.parser.ParsedPage.soup directly, same as the other
analytics/* modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "tagcommander"

# e.g. https://cdn.tagcommander.com/1234/tc_MySite_5.js
# or a client CNAME like tags.client.com/.../tc_MySite_5.js
TC_SRC_RE = re.compile(
    r"(?:tagcommander\.com|/tc_)[^\"'\s]*?tc_([\w-]+)_(\d+)\.js",
    re.IGNORECASE,
)
TC_VARS_RE = re.compile(r"\btc_vars\s*=\s*{", re.IGNORECASE)
TC_GLOBAL_RE = re.compile(r"\b(?:window\.)?tC\s*\.\s*(?:event|container)\b", re.IGNORECASE)
TC_ACCOUNT_RE = re.compile(r"cdn\.tagcommander\.com/(\d+)/", re.IGNORECASE)


@dataclass
class TagCommanderDetection:
    detected: bool = False
    container_ids: List[str] = field(default_factory=list)
    account_ids: List[str] = field(default_factory=list)
    tc_vars_found: bool = False
    tc_api_found: bool = False
    script_tag_count: int = 0


def detect_tagcommander(page: ParsedPage) -> TagCommanderDetection:
    """Scans this page's <script> tags for TagCommander/Commanders Act signals."""
    result = TagCommanderDetection()
    container_ids: List[str] = []
    account_ids: List[str] = []

    for tag in page.soup.find_all("script"):
        src = tag.get("src") or ""
        body = tag.string or tag.get_text() or ""

        src_match = TC_SRC_RE.search(src)
        if src_match:
            result.script_tag_count += 1
            container_ids.append(src_match.group(1))

        acct_match = TC_ACCOUNT_RE.search(src)
        if acct_match:
            account_ids.append(acct_match.group(1))

        if TC_VARS_RE.search(body):
            result.tc_vars_found = True

        if TC_GLOBAL_RE.search(body):
            result.tc_api_found = True

    result.container_ids = list(dict.fromkeys(container_ids))
    result.account_ids = list(dict.fromkeys(account_ids))
    result.detected = (
        result.script_tag_count > 0
        or result.tc_vars_found
        or result.tc_api_found
    )
    return result


def check_tagcommander(page: ParsedPage) -> List[dict]:
    """Findings for TagCommander configuration issues. Absence is not itself a finding."""
    detection = detect_tagcommander(page)
    findings: List[dict] = []

    if not detection.detected:
        return findings

    if detection.script_tag_count > 0 and not detection.tc_vars_found:
        findings.append(_finding(
            "info",
            "TagCommander loader present without tc_vars",
            f"{page.url} loads a TagCommander container but no `tc_vars` "
            f"configuration object was found before the loader script.",
            recommendation="Confirm `tc_vars` is declared before the "
                            "TagCommander loader so container-level data "
                            "(page category, environment, etc.) is available "
                            "to tags at fire time.",
        ))

    if len(detection.container_ids) > 1:
        shown = ", ".join(detection.container_ids[:5])
        findings.append(_finding(
            "info",
            "Multiple TagCommander containers detected",
            f"{page.url} references more than one TagCommander container: {shown}.",
            recommendation="Confirm every container listed is meant to be here.",
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
