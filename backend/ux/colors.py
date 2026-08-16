"""
ux/colors.py

Palette-consistency checks: how many distinct color values a page
declares, and whether any get reused often enough to look like an
intentional design system versus a grab-bag of one-off hex codes. This
is a design-consistency lens — accessibility/contrast.py already owns
whether any given foreground/background pair is *readable* (WCAG
ratio); this module doesn't re-check contrast at all, only variety.

Reads inline `style` attributes and `<style>` blocks directly, same
declared-styles-only scope as accessibility/contrast.py and
ux/typography.py — colors that only resolve via external stylesheets
or JS-applied classes aren't visible here.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "ux"
CATEGORY = "colors"

# Distinct declared colors beyond this starts to look like an unmanaged palette
# rather than a deliberate design system (brand + neutrals + a couple of accents).
MAX_DISTINCT_COLORS = 12
MIN_DECLARATIONS_TO_JUDGE = 6  # too few declared colors for "too many" to be meaningful

_DECL_RE = re.compile(r"([\w-]+)\s*:\s*([^;]+)")
_STYLE_RULE_RE = re.compile(r"([^{}]+)\{([^{}]+)\}")
_HEX_RE = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b")
_RGB_RE = re.compile(r"rgba?\([^)]+\)")

_COLOR_PROPS = ("color", "background-color", "background", "border-color", "fill", "stroke")


def check_colors(page: ParsedPage) -> List[dict]:
    """Findings for an unusually large or apparently unmanaged declared color palette."""
    colors = _collect_colors(page)
    if len(colors) < MIN_DECLARATIONS_TO_JUDGE:
        return []

    distinct = Counter(colors)
    if len(distinct) <= MAX_DISTINCT_COLORS:
        return []

    one_offs = sum(1 for _color, count in distinct.items() if count == 1)
    one_off_ratio = one_offs / len(distinct)

    examples = ", ".join(list(distinct.keys())[:6])
    findings = [_finding(
        "info",
        "Large number of distinct declared colors",
        f"{page.url} declares {len(distinct)} distinct color values across "
        f"{len(colors)} color-related declarations (e.g. {examples}, ...). A page drawing "
        "from a large, loosely-defined palette instead of a small set of reused brand "
        "colors tends to read as visually inconsistent, and makes future design changes "
        "harder since colors aren't centralized.",
        recommendation="Consolidate toward a defined palette (brand color(s), a small "
                        "neutral scale, and one or two accents) expressed as CSS custom "
                        "properties or design tokens, and reuse those everywhere instead of "
                        "one-off hex values.",
    )]

    if one_off_ratio > 0.7:
        findings.append(_finding(
            "info",
            "Most declared colors are used only once",
            f"{one_offs} of {len(distinct)} distinct colors on {page.url} appear in only a "
            "single declaration each. Colors used exactly once are a common sign they were "
            "picked ad hoc for that one element rather than pulled from a shared palette.",
            recommendation="Audit one-off colors and either map them onto existing palette "
                            "values or formally add them to the palette if they're genuinely "
                            "new brand colors.",
        ))

    return findings


def _collect_colors(page: ParsedPage) -> List[str]:
    colors: List[str] = []
    for tag in page.soup.find_all(style=True):
        colors += _extract_from_block(tag.get("style", ""))
    for style_tag in page.soup.find_all("style"):
        css = style_tag.string or style_tag.get_text() or ""
        for _selector, body in _STYLE_RULE_RE.findall(css):
            colors += _extract_from_block(body)
    return colors


def _extract_from_block(css_text: str) -> List[str]:
    found: List[str] = []
    for prop, raw_value in _DECL_RE.findall(css_text or ""):
        if prop.strip().lower() not in _COLOR_PROPS:
            continue
        value = raw_value.strip().lower()
        if value in ("transparent", "inherit", "initial", "unset", "none", "currentcolor"):
            continue
        if _HEX_RE.match(value) or _RGB_RE.match(value):
            found.append(_normalize(value))
    return found


def _normalize(value: str) -> str:
    """Expands 3-digit hex to 6-digit so #fff and #ffffff count as the same color."""
    if value.startswith("#") and len(value) == 4:
        return "#" + "".join(c * 2 for c in value[1:])
    return value


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
