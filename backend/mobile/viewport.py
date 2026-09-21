"""
mobile/viewport.py

Checks the single most load-bearing tag for mobile rendering: <meta
name="viewport">. Without it (or with the wrong values) a mobile
browser renders the page at a desktop-width virtual viewport and
scales it down, which is the classic "tiny zoomed-out site" complaint
— every other mobile/ check assumes this is set correctly, so it's
worth flagging on its own with the most specific findings.

Reads crawler.parser.ParsedPage.meta, which already lowercases meta
`name` keys, so this never touches page.soup directly.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from crawler.parser import ParsedPage

MODULE = "mobile"
CATEGORY = "viewport"

_CONTENT_PAIR_RE = re.compile(r"([\w-]+)\s*=\s*([^,]+)")


def check_viewport(page: ParsedPage) -> List[dict]:
    """Findings for a missing or misconfigured viewport meta tag."""
    content = page.meta.get("viewport")

    if content is None:
        return [_finding(
            "critical",
            "Missing viewport meta tag",
            f"{page.url} has no <meta name=\"viewport\"> tag. Mobile browsers fall back to "
            "rendering at a desktop-width virtual viewport (typically 980px) and scaling the "
            "result down, making text and tap targets tiny until the user manually zooms.",
            recommendation="Add <meta name=\"viewport\" content=\"width=device-width, "
                            "initial-scale=1\"> to the page <head>.",
        )]

    values = _parse_content(content)
    findings: List[dict] = []

    width = values.get("width")
    if width is None:
        findings.append(_finding(
            "warning",
            "Viewport meta tag missing width=device-width",
            f"{page.url}'s viewport tag (\"{content}\") doesn't set width=device-width, so "
            "the browser still picks its own default layout width instead of matching the "
            "device's screen.",
            recommendation="Include width=device-width in the viewport content value.",
        ))
    elif width.lower() != "device-width":
        findings.append(_finding(
            "warning",
            "Viewport width is a fixed value instead of device-width",
            f"{page.url} sets viewport width to a fixed value (\"{width}\") rather than "
            "device-width, which breaks the layout on any screen a different size than "
            "whatever that fixed value assumes.",
            recommendation="Use width=device-width so the layout matches every screen size.",
        ))

    if values.get("user-scalable", "").lower() in ("no", "0"):
        findings.append(_finding(
            "warning",
            "Pinch-to-zoom disabled",
            f"{page.url} sets user-scalable=no, preventing users from zooming in. This is a "
            "WCAG 1.4.4 (Resize Text) failure and disproportionately affects users with low "
            "vision who rely on pinch-to-zoom to read content.",
            recommendation="Remove user-scalable=no so users can zoom the page themselves.",
        ))

    max_scale = values.get("maximum-scale")
    if max_scale is not None:
        try:
            if float(max_scale) < 2:
                findings.append(_finding(
                    "info",
                    "Viewport maximum-scale restricts zoom",
                    f"{page.url} caps maximum-scale at {max_scale}, limiting how far users "
                    "can zoom in even though pinch-to-zoom itself isn't fully disabled.",
                    recommendation="Remove maximum-scale, or set it to at least 5 so users "
                                    "retain meaningful zoom range.",
                ))
        except ValueError:
            pass

    return findings


def _parse_content(content: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for key, value in _CONTENT_PAIR_RE.findall(content or ""):
        values[key.strip().lower()] = value.strip()
    return values


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
