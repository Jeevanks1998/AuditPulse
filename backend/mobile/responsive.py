"""
mobile/responsive.py

Static signals that a layout was built desktop-first and never
adapted for narrow screens: hard-coded pixel widths wide enough to
force horizontal scrolling on a phone, and the total absence of any
@media breakpoint despite the page shipping real CSS. Like
ux/typography.py, this only sees declared styles in inline `style`
attributes and <style> blocks — an external stylesheet with all the
right breakpoints in it is invisible here, so a clean result isn't
proof the page is responsive, only that nothing obviously wrong showed
up in what's inline.
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "mobile"
CATEGORY = "responsive"

# Narrowest common phone viewport (iPhone SE-class); a hard-coded width
# past this forces horizontal scrolling on real devices, not just a
# hypothetical small screen.
MIN_SAFE_FIXED_WIDTH_PX = 400

_DECL_RE = re.compile(r"([\w-]+)\s*:\s*([^;]+)")
_STYLE_RULE_RE = re.compile(r"([^{}]+)\{([^{}]+)\}")
_PX_RE = re.compile(r"^([\d.]+)px$")
_MEDIA_QUERY_RE = re.compile(r"@media\b", re.IGNORECASE)

MAX_EXAMPLES = 5


def check_responsive(page: ParsedPage) -> List[dict]:
    """Findings for fixed-width layout blocks and missing responsive breakpoints."""
    style_blocks = _style_block_text(page)
    findings: List[dict] = []

    findings += _check_fixed_widths(page)
    findings += _check_media_queries(page, style_blocks)
    return findings


def _check_fixed_widths(page: ParsedPage) -> List[dict]:
    offenders = []

    for tag in page.soup.find_all(style=True):
        width = _fixed_width_px(tag.get("style", ""))
        if width is not None and width > MIN_SAFE_FIXED_WIDTH_PX:
            offenders.append((tag.name, width))

    for _selector, body in _STYLE_RULE_RE.findall(_style_block_text(page)):
        width = _fixed_width_px(body)
        if width is not None and width > MIN_SAFE_FIXED_WIDTH_PX:
            offenders.append(("<style> rule", width))

    if not offenders:
        return []

    widest = max(w for _, w in offenders)
    examples = ", ".join(f"{name} ({w:.0f}px)" for name, w in offenders[:MAX_EXAMPLES])
    return [_finding(
        "warning",
        "Fixed-width elements wider than a phone screen",
        f"{page.url} declares {len(offenders)} element(s) with a hard-coded width in px, up "
        f"to {widest:.0f}px, with no accompanying max-width or percentage-based sizing: "
        f"{examples}. On a phone screen (as narrow as ~375px) this forces horizontal "
        "scrolling instead of the content reflowing to fit.",
        recommendation="Replace fixed px widths on layout containers with max-width, "
                        "percentages, or fluid units (%, vw, clamp()) so content reflows to "
                        "the viewport instead of overflowing it.",
    )]


def _check_media_queries(page: ParsedPage, style_blocks: str) -> List[dict]:
    if not style_blocks.strip():
        return []  # no inline CSS to judge either way
    if _MEDIA_QUERY_RE.search(style_blocks):
        return []

    return [_finding(
        "info",
        "No responsive breakpoints found in inline CSS",
        f"{page.url} has <style> block CSS but no @media query anywhere in it, suggesting "
        "the visible styling doesn't change across screen sizes. (An external stylesheet "
        "could still carry breakpoints — this only inspects inline and <style>-block CSS.)",
        recommendation="Add @media breakpoints (or confirm they exist in an external "
                        "stylesheet) so layout, font sizes, and spacing adapt for narrow "
                        "screens.",
    )]


def _fixed_width_px(css_text: str) -> Optional[float]:
    raw = dict(_DECL_RE.findall(css_text or ""))
    width = raw.get("width")
    if not width:
        return None
    match = _PX_RE.match(width.strip())
    if not match:
        return None
    if "max-width" in raw:
        return None  # a max-width alongside width still lets it shrink
    return float(match.group(1))


def _style_block_text(page: ParsedPage) -> str:
    parts = []
    for style_tag in page.soup.find_all("style"):
        parts.append(style_tag.string or style_tag.get_text() or "")
    return "\n".join(parts)


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
