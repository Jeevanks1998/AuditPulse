"""
ux/typography.py

Static checks on declared typography: base body text size, line-height
(leading), and how many distinct font families are declared. All
read directly from inline `style` attributes and `<style>` blocks in
crawler.parser.ParsedPage.soup, the same declared-styles-only approach
accessibility/contrast.py uses for color pairs — external stylesheets
and computed/cascaded values aren't visible here, so this catches
obvious hard-coded issues, not the full rendered picture.

This is a design-consistency lens (does the page read comfortably,
does the type system look intentional) rather than accessibility/
contrast.py's WCAG-ratio lens — they look at overlapping markup for
different reasons and can both fire on the same page.
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "ux"
CATEGORY = "typography"

MIN_BODY_FONT_PX = 14          # below this, body copy is commonly reported as "too small"
COMFORTABLE_BODY_FONT_PX = 16  # widely-cited comfortable reading baseline
MIN_LINE_HEIGHT_RATIO = 1.3    # unitless line-height below this reads as cramped
MAX_FONT_FAMILIES = 4          # distinct font-family declarations before it looks inconsistent

_DECL_RE = re.compile(r"([\w-]+)\s*:\s*([^;]+)")
_STYLE_RULE_RE = re.compile(r"([^{}]+)\{([^{}]+)\}")
_PX_RE = re.compile(r"^([\d.]+)px$")
_PT_RE = re.compile(r"^([\d.]+)pt$")
_UNITLESS_RE = re.compile(r"^([\d.]+)$")


def check_typography(page: ParsedPage) -> List[dict]:
    """Findings for small body text, cramped line-height, and font-family sprawl."""
    declarations = _all_declarations(page)
    if not declarations:
        return []

    findings: List[dict] = []
    findings += _check_body_font_size(page, declarations)
    findings += _check_line_height(page, declarations)
    findings += _check_font_family_count(page, declarations)
    return findings


def _check_body_font_size(page: ParsedPage, declarations: list) -> List[dict]:
    sizes_px = [d["font-size-px"] for d in declarations if d.get("font-size-px") is not None]
    if not sizes_px:
        return []

    smallest = min(sizes_px)
    if smallest >= COMFORTABLE_BODY_FONT_PX:
        return []

    severity = "warning" if smallest < MIN_BODY_FONT_PX else "info"
    return [_finding(
        severity,
        "Small declared font size",
        f"{page.url} declares a font-size as small as {smallest:.0f}px. Body text under "
        f"{COMFORTABLE_BODY_FONT_PX}px is commonly reported as uncomfortable to read, "
        "especially on mobile, and text under 12px is difficult for most readers regardless "
        "of device.",
        recommendation=f"Set body copy to at least {COMFORTABLE_BODY_FONT_PX}px "
                        "(1rem at the default root size), reserving smaller sizes for "
                        "genuinely secondary text like captions or fine print.",
    )]


def _check_line_height(page: ParsedPage, declarations: list) -> List[dict]:
    ratios = [d["line-height-ratio"] for d in declarations if d.get("line-height-ratio") is not None]
    if not ratios:
        return []

    tightest = min(ratios)
    if tightest >= MIN_LINE_HEIGHT_RATIO:
        return []

    return [_finding(
        "info",
        "Tight line-height on declared text",
        f"{page.url} declares a line-height as tight as {tightest:.2f} (unitless ratio). "
        f"Below roughly {MIN_LINE_HEIGHT_RATIO}, lines of text sit close enough together "
        "that they become harder to track while reading, particularly for longer passages.",
        recommendation=f"Use a line-height of at least {MIN_LINE_HEIGHT_RATIO} for body "
                        "copy; tighter values are fine for large display headings only.",
    )]


def _check_font_family_count(page: ParsedPage, declarations: list) -> List[dict]:
    families = {d["font-family"] for d in declarations if d.get("font-family")}
    if len(families) <= MAX_FONT_FAMILIES:
        return []

    examples = ", ".join(sorted(families)[:MAX_FONT_FAMILIES + 1])
    return [_finding(
        "info",
        "Many distinct font families declared",
        f"{page.url} declares {len(families)} different font-family values ({examples}, "
        "...). A large number of typefaces on one page tends to read as inconsistent "
        "rather than intentional, and adds page weight if each pulls in a separate web "
        "font file.",
        recommendation="Standardize on a small type system — typically one family for "
                        "headings and one for body text, using weight/size variation "
                        "instead of additional families for emphasis.",
    )]


def _all_declarations(page: ParsedPage) -> list:
    """Every color/typography-relevant declaration block found inline or in <style> tags."""
    blocks: list = []
    for tag in page.soup.find_all(style=True):
        blocks.append(_parse_block(tag.get("style", "")))
    for style_tag in page.soup.find_all("style"):
        css = style_tag.string or style_tag.get_text() or ""
        for _selector, body in _STYLE_RULE_RE.findall(css):
            blocks.append(_parse_block(body))
    return [b for b in blocks if b]


def _parse_block(css_text: str) -> Optional[dict]:
    raw = dict(_DECL_RE.findall(css_text or ""))
    if not raw:
        return None

    out: dict = {}
    if "font-size" in raw:
        out["font-size-px"] = _to_px(raw["font-size"].strip())
    if "line-height" in raw:
        out["line-height-ratio"] = _line_height_ratio(raw["line-height"].strip(), out.get("font-size-px"))
    if "font-family" in raw:
        primary = raw["font-family"].split(",")[0].strip().strip("'\"")
        if primary:
            out["font-family"] = primary.lower()

    return out or None


def _to_px(value: str) -> Optional[float]:
    match = _PX_RE.match(value)
    if match:
        return float(match.group(1))
    match = _PT_RE.match(value)
    if match:
        return float(match.group(1)) * 1.333
    return None


def _line_height_ratio(value: str, font_px: Optional[float]) -> Optional[float]:
    match = _UNITLESS_RE.match(value)
    if match:
        return float(match.group(1))
    px_match = _PX_RE.match(value)
    if px_match and font_px:
        return float(px_match.group(1)) / font_px
    return None


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
