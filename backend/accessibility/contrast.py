"""
accessibility/contrast.py

Page-level color-contrast checks against WCAG 2.x success criterion
1.4.3 (AA, 4.5:1 normal text / 3:1 large text) and 1.4.6 (AAA, 7:1 /
4.5:1). This is a best-effort, static check: without a browser actually
computing the cascade, we can only see color/background-color pairs
that are declared explicitly, either inline (`style="color:...;
background-color:..."`) or as a same-selector declaration in a `<style>`
block. Colors that only resolve via inherited ancestors, external
stylesheets, or JS-applied classes are invisible to this module —
accessibility/axe.py (Lighthouse's color-contrast audit, which renders
the real page) is the source of truth for those; this module exists to
catch obvious hard-coded failures cheaply and without a network call.

Reads crawler.parser.ParsedPage.soup directly, since neither inline
style attributes nor <style> block contents are pulled out into
ParsedPage's normal fields.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from crawler.parser import ParsedPage

MODULE = "accessibility"
CATEGORY = "contrast"

AA_NORMAL_RATIO = 4.5
AA_LARGE_RATIO = 3.0
# A declared font-size (px) at/above this is treated as "large text" for
# the relaxed 3:1 threshold, mirroring the ~18pt/14pt-bold WCAG definition.
LARGE_TEXT_PX = 24

_COLOR_DECL_RE = re.compile(r"([\w-]+)\s*:\s*([^;]+)")
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB_RE = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*[\d.]+\s*)?\)$")
_STYLE_RULE_RE = re.compile(r"([^{}]+)\{([^{}]+)\}")

_NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "green": (0, 128, 0), "blue": (0, 0, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "silver": (192, 192, 192), "yellow": (255, 255, 0),
    "orange": (255, 165, 0), "purple": (128, 0, 128), "navy": (0, 0, 128),
}

MAX_PAIRS_REPORTED = 5  # cap findings per page so one templated block doesn't flood the report


def check_contrast(page: ParsedPage) -> List[dict]:
    """Findings for declared color/background-color pairs that fail WCAG AA contrast."""
    pairs = _inline_style_pairs(page) + _style_block_pairs(page)
    if not pairs:
        return []

    failures = []
    for selector_hint, fg, bg, font_px in pairs:
        ratio = _contrast_ratio(fg, bg)
        if ratio is None:
            continue
        threshold = AA_LARGE_RATIO if font_px and font_px >= LARGE_TEXT_PX else AA_NORMAL_RATIO
        if ratio < threshold:
            failures.append((selector_hint, fg, bg, ratio, threshold))

    if not failures:
        return []

    failures.sort(key=lambda f: f[3])  # worst ratio first
    shown = failures[:MAX_PAIRS_REPORTED]
    findings: List[dict] = []
    for selector_hint, fg, bg, ratio, threshold in shown:
        severity = "critical" if ratio < threshold * 0.7 else "warning"
        findings.append(_finding(
            severity,
            "Insufficient color contrast",
            f"On {page.url}, {selector_hint} declares text color {fg} on background {bg}, "
            f"a contrast ratio of {ratio:.2f}:1 (WCAG AA requires at least {threshold:.1f}:1). "
            "Low-contrast text is difficult or impossible to read for users with low vision "
            "or color-vision deficiencies.",
            recommendation="Darken the text color, lighten the background (or vice versa) "
                            f"until the ratio is at least {threshold:.1f}:1. A contrast "
                            "checker (e.g. WebAIM's) makes this quick to iterate on.",
        ))

    if len(failures) > MAX_PAIRS_REPORTED:
        findings.append(_finding(
            "info",
            "Additional low-contrast pairs not shown",
            f"{page.url} has {len(failures) - MAX_PAIRS_REPORTED} more declared color pairs "
            f"below WCAG AA contrast beyond the {MAX_PAIRS_REPORTED} worst shown above.",
            recommendation="Run a full-page automated contrast audit (see the axe/Lighthouse "
                            "findings) to see every instance, not just declared inline pairs.",
        ))

    return findings


def _inline_style_pairs(page: ParsedPage) -> List[Tuple[str, str, str, Optional[float]]]:
    pairs: List[Tuple[str, str, str, Optional[float]]] = []
    for tag in page.soup.find_all(style=True):
        decls = _parse_declarations(tag.get("style", ""))
        fg, bg, font_px = decls.get("color"), decls.get("background-color") or decls.get("background"), decls.get("font-size")
        if fg and bg:
            label = f"<{tag.name}> (inline style)"
            pairs.append((label, fg, bg, font_px))
    return pairs


def _style_block_pairs(page: ParsedPage) -> List[Tuple[str, str, str, Optional[float]]]:
    pairs: List[Tuple[str, str, str, Optional[float]]] = []
    for style_tag in page.soup.find_all("style"):
        css = style_tag.string or style_tag.get_text() or ""
        for selector, body in _STYLE_RULE_RE.findall(css):
            decls = _parse_declarations(body)
            fg = decls.get("color")
            bg = decls.get("background-color") or decls.get("background")
            font_px = decls.get("font-size")
            if fg and bg:
                pairs.append((f"selector `{selector.strip()[:60]}`", fg, bg, font_px))
    return pairs


def _parse_declarations(css_text: str) -> dict:
    """{'color': '#normalized', 'background-color': '#normalized', 'font-size': px_float_or_None}."""
    out: dict = {}
    for prop, raw_value in _COLOR_DECL_RE.findall(css_text or ""):
        prop = prop.strip().lower()
        raw_value = raw_value.strip()
        if prop in ("color", "background-color", "background"):
            rgb = _parse_color(raw_value)
            if rgb:
                out[prop] = raw_value if prop != "background" else raw_value
                out[f"_{prop}_rgb"] = rgb
        elif prop == "font-size":
            out["font-size"] = _parse_font_size_px(raw_value)
    # promote raw rgb tuples back onto the simple keys expected by callers
    result = {}
    if "_color_rgb" in out:
        result["color"] = out["color"]
    if "_background-color_rgb" in out:
        result["background-color"] = out["background-color"]
    elif "_background_rgb" in out:
        result["background-color"] = out["background"]
    if "font-size" in out:
        result["font-size"] = out["font-size"]
    return result


def _parse_font_size_px(value: str) -> Optional[float]:
    match = re.match(r"^([\d.]+)px$", value.strip())
    if match:
        return float(match.group(1))
    match = re.match(r"^([\d.]+)pt$", value.strip())
    if match:
        return float(match.group(1)) * 1.333  # pt -> px
    return None


def _parse_color(value: str) -> Optional[Tuple[int, int, int]]:
    value = value.strip().lower()
    if value in _NAMED_COLORS:
        return _NAMED_COLORS[value]
    if _HEX_RE.match(value):
        hexpart = value.lstrip("#")
        if len(hexpart) == 3:
            hexpart = "".join(c * 2 for c in hexpart)
        return tuple(int(hexpart[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    match = _RGB_RE.match(value)
    if match:
        return tuple(int(match.group(i)) for i in (1, 2, 3))  # type: ignore[return-value]
    return None


def _contrast_ratio(fg: str, bg: str) -> Optional[float]:
    fg_rgb, bg_rgb = _parse_color(fg), _parse_color(bg)
    if not fg_rgb or not bg_rgb:
        return None
    l1, l2 = _relative_luminance(fg_rgb), _relative_luminance(bg_rgb)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _relative_luminance(rgb: Tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        c_srgb = c / 255.0
        return c_srgb / 12.92 if c_srgb <= 0.03928 else ((c_srgb + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
