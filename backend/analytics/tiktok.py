"""
analytics/tiktok.py

Detects the TikTok Pixel. Unlike most other tags here, TikTok's base
snippet doesn't add a <script src="..."> tag directly — it's a small
inline IIFE that defines `ttq`, then has ttq.load('PIXEL_ID') fetch
the real events.js loader itself at runtime. So the reliable signals
are all inline: the ttq.load(...) call (which carries the pixel ID)
and the ttq.page() call that fires the initial page-view event.

Reads crawler.parser.ParsedPage.soup directly, same rationale as the
other analytics/* modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "tiktok"

LOADER_HINT_RE = re.compile(r"analytics\.tiktok\.com/i18n/pixel/events\.js", re.IGNORECASE)
LOAD_CALL_RE = re.compile(r"ttq\.load\(\s*['\"]([A-Z0-9]+)['\"]", re.IGNORECASE)
PAGE_CALL_RE = re.compile(r"\bttq\.page\s*\(\s*\)")


@dataclass
class TikTokDetection:
    detected: bool = False
    pixel_ids: List[str] = field(default_factory=list)
    page_call_found: bool = False


def detect_tiktok(page: ParsedPage) -> TikTokDetection:
    """Scans this page's <script> tags for TikTok Pixel signals."""
    result = TikTokDetection()
    pixel_ids: List[str] = []
    found_hint = False

    for tag in page.soup.find_all("script"):
        src = tag.get("src") or ""
        body = tag.string or tag.get_text() or ""

        if LOADER_HINT_RE.search(src) or LOADER_HINT_RE.search(body):
            found_hint = True

        pixel_ids += LOAD_CALL_RE.findall(body)
        if PAGE_CALL_RE.search(body):
            result.page_call_found = True

    result.pixel_ids = list(dict.fromkeys(pixel_ids))
    result.detected = bool(result.pixel_ids) or found_hint
    return result


def check_tiktok(page: ParsedPage) -> List[dict]:
    """Findings for TikTok Pixel configuration issues. Absence of the pixel is not itself a finding."""
    detection = detect_tiktok(page)
    findings: List[dict] = []

    if not detection.detected:
        return findings

    if detection.pixel_ids and not detection.page_call_found:
        findings.append(_finding(
            "warning",
            "TikTok Pixel loaded without a page-view call",
            f"{page.url} calls ttq.load(...) but no ttq.page() call was found, so "
            "this page may not register a standard PageView event.",
            recommendation="Add ttq.page() after ttq.load(...) unless the page view "
                            "is intentionally tracked elsewhere.",
        ))

    if len(detection.pixel_ids) > 1:
        shown = ", ".join(detection.pixel_ids[:5])
        findings.append(_finding(
            "info",
            "Multiple TikTok Pixel IDs detected",
            f"{page.url} references more than one TikTok Pixel ID: {shown}.",
            recommendation="Confirm every pixel ID listed is meant to fire on this page.",
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
