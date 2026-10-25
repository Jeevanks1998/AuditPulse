"""
Detects the Meta (Facebook) Pixel: fbevents.js, fbq('init'/'track') calls and the <noscript> fallback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "analytics"
CATEGORY = "meta_pixel"

LOADER_SRC_RE = re.compile(r"connect\.facebook\.net/[^'\"]*fbevents\.js", re.IGNORECASE)
INIT_CALL_RE = re.compile(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d+)['\"]", re.IGNORECASE)
TRACK_PAGEVIEW_RE = re.compile(r"fbq\(\s*['\"]track['\"]\s*,\s*['\"]PageView['\"]", re.IGNORECASE)
NOSCRIPT_FALLBACK_RE = re.compile(r"facebook\.com/tr\?id=(\d+)", re.IGNORECASE)


@dataclass
class MetaPixelDetection:
    detected: bool = False
    pixel_ids: List[str] = field(default_factory=list)
    loader_found: bool = False
    pageview_fired: bool = False
    has_noscript_fallback: bool = False


def detect_meta_pixel(page: ParsedPage) -> MetaPixelDetection:
    """Looks for the Meta Pixel in <script> / <noscript> tags."""
    result = MetaPixelDetection()
    pixel_ids: List[str] = []

    for tag in page.soup.find_all("script"):
        src = tag.get("src") or ""
        body = tag.string or tag.get_text() or ""

        if LOADER_SRC_RE.search(src):
            result.loader_found = True

        pixel_ids += INIT_CALL_RE.findall(body)
        if TRACK_PAGEVIEW_RE.search(body):
            result.pageview_fired = True

    for tag in page.soup.find_all("noscript"):
        text = str(tag)
        match = NOSCRIPT_FALLBACK_RE.search(text)
        if match:
            result.has_noscript_fallback = True
            pixel_ids.append(match.group(1))

    result.pixel_ids = list(dict.fromkeys(pixel_ids))
    result.detected = result.loader_found or bool(result.pixel_ids)
    return result


def check_meta_pixel(page: ParsedPage) -> List[dict]:
    """Findings for Meta Pixel problems. No pixel at all is not a finding."""
    detection = detect_meta_pixel(page)
    findings: List[dict] = []

    if not detection.detected:
        return findings

    if detection.pixel_ids and not detection.has_noscript_fallback:
        findings.append(_finding(
            "warning",
            "Meta Pixel noscript fallback is missing",
            f"{page.url} initializes the Meta Pixel but has no matching "
            "<noscript><img src=\".../tr?id=...\"> fallback, so visitors with "
            "JavaScript disabled or blocked generate no pixel hit at all.",
            recommendation="Add the noscript <img> fallback from Meta's pixel base "
                            "code alongside the JS snippet.",
        ))

    if detection.loader_found and not detection.pixel_ids:
        findings.append(_finding(
            "warning",
            "Meta Pixel loader present with no init() call",
            f"{page.url} loads fbevents.js but no fbq('init', ...) call with a pixel "
            "ID was found — the pixel is loaded but not actually configured.",
            recommendation="Add an fbq('init', 'PIXEL_ID') call after the loader.",
        ))

    if detection.pixel_ids and not detection.pageview_fired:
        findings.append(_finding(
            "info",
            "Meta Pixel initialized without a PageView event",
            f"{page.url} initializes the Meta Pixel but no fbq('track', 'PageView') "
            "call was found, so this page may not register as a visit.",
            recommendation="Add fbq('track', 'PageView') after fbq('init', ...) "
                            "unless PageView is intentionally suppressed here.",
        ))

    if len(detection.pixel_ids) > 1:
        shown = ", ".join(detection.pixel_ids[:5])
        findings.append(_finding(
            "info",
            "Multiple Meta Pixel IDs detected",
            f"{page.url} references more than one Pixel ID: {shown}.",
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
