"""
Checks the dataLayer (the array tag managers read events from): does it
exist, is it pushed to, and which events appear. GTM's own events and
page_view are separated from custom events.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "data_layer"

INIT_RE = re.compile(r"dataLayer\s*=\s*(?:window\.dataLayer\s*\|\|\s*)?\[\s*\]")
PUSH_RE = re.compile(r"dataLayer\.push\s*\(\s*(\{.*?\})\s*\)", re.DOTALL)
EVENT_NAME_RE = re.compile(r"['\"]event['\"]\s*:\s*['\"]([^'\"]+)['\"]")

PAGEVIEW_EVENT_NAMES = {"gtm.js", "gtm.dom", "gtm.load", "page_view", "pageview"}

MAX_EVENT_NAMES_REPORTED = 10


@dataclass
class DataLayerDetection:
    present: bool = False  # dataLayer mentioned at all
    explicitly_initialized: bool = False  # `dataLayer = window.dataLayer || []` found
    push_call_count: int = 0
    event_names: List[str] = field(default_factory=list)
    pageview_events: int = 0
    custom_events: int = 0


def detect_data_layer(page: ParsedPage) -> DataLayerDetection:
    """Looks for dataLayer set-up and pushes in inline scripts."""
    result = DataLayerDetection()
    event_names: List[str] = []

    for tag in page.soup.find_all("script"):
        if tag.get("src"):
            continue  # only inline scripts show the pushed data
        body = tag.string or tag.get_text() or ""
        if not body or "dataLayer" not in body:
            continue

        result.present = True
        if INIT_RE.search(body):
            result.explicitly_initialized = True

        pushes = PUSH_RE.findall(body)
        result.push_call_count += len(pushes)
        for payload in pushes:
            event_names += EVENT_NAME_RE.findall(payload)

    result.event_names = event_names[:MAX_EVENT_NAMES_REPORTED]
    result.pageview_events = sum(1 for name in event_names if name in PAGEVIEW_EVENT_NAMES)
    result.custom_events = sum(1 for name in event_names if name not in PAGEVIEW_EVENT_NAMES)
    return result


def check_data_layer(page: ParsedPage, gtm_detected: bool = False) -> List[dict]:
    """Findings for dataLayer problems; flags GTM installed with no dataLayer activity."""
    detection = detect_data_layer(page)
    findings: List[dict] = []

    if gtm_detected and not detection.present:
        findings.append(_finding(
            "warning",
            "GTM installed but no dataLayer activity found",
            f"Google Tag Manager is installed on {page.url} but no dataLayer.push(...) "
            "calls were found in the page's inline scripts, so only GTM's own "
            "built-in events (page load, clicks configured as triggers) are "
            "available — no custom events are being fed in.",
            recommendation="Push relevant events (e.g. form submissions, purchases) "
                            "into dataLayer so GTM triggers can use them.",
        ))

    if detection.present and detection.push_call_count > 0 and not detection.explicitly_initialized:
        findings.append(_finding(
            "info",
            "dataLayer is pushed to without a visible initialization",
            f"{page.url} calls dataLayer.push(...) but no "
            "`dataLayer = window.dataLayer || []`-style initialization was found in "
            "this page's own scripts — it may be initialized by GTM's own snippet "
            "instead, which is fine, but couldn't be confirmed here.",
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
