"""
analytics/data_layer.py

Checks for the GTM/GA4-style `dataLayer` convention: an array most tag
managers read events from, initialized as `window.dataLayer =
window.dataLayer || []` and fed via `dataLayer.push({...})` calls. This
module doesn't care which tag manager owns it — it just looks at
whether one exists, whether it's ever pushed to, and what event names
show up, splitting GTM's own built-in events ('gtm.js', 'gtm.dom',
'gtm.load') and a conventional 'page_view'/'pageview' from anything
else (treated as a custom event).

Reads crawler.parser.ParsedPage.soup directly, same rationale as the
other analytics/* modules.
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
    present: bool = False  # dataLayer referenced at all (init or push)
    explicitly_initialized: bool = False  # a `dataLayer = window.dataLayer || []`-style line was found
    push_call_count: int = 0
    event_names: List[str] = field(default_factory=list)
    pageview_events: int = 0
    custom_events: int = 0


def detect_data_layer(page: ParsedPage) -> DataLayerDetection:
    """Scans this page's inline <script> tags for dataLayer init/push activity."""
    result = DataLayerDetection()
    event_names: List[str] = []

    for tag in page.soup.find_all("script"):
        if tag.get("src"):
            continue  # only inline scripts can contain literal push() payloads
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
    """
    Findings for dataLayer setup issues. `gtm_detected` (from
    analytics.gtm.detect_gtm(page).detected) lets this flag the specific
    case of GTM being installed with no dataLayer activity anywhere on
    the page, which usually means events aren't reaching it.
    """
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
