"""
mobile/touch.py

Checks aimed at finger-sized interaction rather than pointer/keyboard
interaction: declared touch targets smaller than a comfortable tap
area, and interactions that only fire on :hover with no touch-usable
equivalent (a mouse-only pattern that a touchscreen can't trigger at
all). Reads crawler.parser.ParsedPage.soup for interactive elements
and <style> blocks — same declared-styles-only lens as
mobile/responsive.py and ux/typography.py.
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "mobile"
CATEGORY = "touch"

# WCAG 2.5.8 (AA) minimum; WCAG 2.5.5 (AAA) recommends 44px. 24px is the
# floor below which a target is flagged regardless of context.
MIN_TOUCH_TARGET_PX = 24
COMFORTABLE_TOUCH_TARGET_PX = 44

_DECL_RE = re.compile(r"([\w-]+)\s*:\s*([^;]+)")
_STYLE_RULE_RE = re.compile(r"([^{}]+)\{([^{}]+)\}")
_PX_RE = re.compile(r"^([\d.]+)px$")
_HOVER_SELECTOR_RE = re.compile(r"([^{}]+):hover\s*\{([^{}]+)\}", re.IGNORECASE)

INTERACTIVE_TAGS = ("a", "button")
MAX_EXAMPLES = 5


def check_touch_targets(page: ParsedPage) -> List[dict]:
    """Findings for undersized tap targets and hover-only interactive styling."""
    findings: List[dict] = []
    findings += _check_small_targets(page)
    findings += _check_hover_only(page)
    return findings


def _check_small_targets(page: ParsedPage) -> List[dict]:
    undersized = []
    critical_count = 0

    for tag_name in INTERACTIVE_TAGS:
        for tag in page.soup.find_all(tag_name, style=True):
            size = _declared_square_px(tag.get("style", ""))
            if size is None:
                continue
            if size < MIN_TOUCH_TARGET_PX:
                critical_count += 1
                undersized.append((tag_name, size))
            elif size < COMFORTABLE_TOUCH_TARGET_PX:
                undersized.append((tag_name, size))

    if not undersized:
        return []

    examples = ", ".join(f"<{name}> ({size:.0f}px)" for name, size in undersized[:MAX_EXAMPLES])
    severity = "warning" if critical_count else "info"
    return [_finding(
        severity,
        "Touch targets smaller than recommended",
        f"{page.url} declares {len(undersized)} tappable element(s) sized under "
        f"{COMFORTABLE_TOUCH_TARGET_PX}px in both dimensions: {examples}. Targets under "
        f"~{MIN_TOUCH_TARGET_PX}px are hard to hit reliably with a finger; the WCAG 2.5.8 "
        f"minimum is {MIN_TOUCH_TARGET_PX}px, and {COMFORTABLE_TOUCH_TARGET_PX}px is the "
        "generally recommended comfortable size.",
        recommendation=f"Size tappable buttons and links to at least "
                        f"{COMFORTABLE_TOUCH_TARGET_PX}x{COMFORTABLE_TOUCH_TARGET_PX}px "
                        "(including padding), or increase spacing around smaller targets so "
                        "adjacent ones aren't easy to mis-tap.",
    )]


def _check_hover_only(page: ParsedPage) -> List[dict]:
    hover_selectors = set()
    non_hover_selectors = set()

    for style_tag in page.soup.find_all("style"):
        css = style_tag.string or style_tag.get_text() or ""
        for selector, _body in _HOVER_SELECTOR_RE.findall(css):
            hover_selectors.add(_base_selector(selector))
        for selector, _body in _STYLE_RULE_RE.findall(css):
            if ":hover" not in selector and (":focus" in selector or ":active" in selector):
                non_hover_selectors.add(_base_selector(selector))

    hover_only = hover_selectors - non_hover_selectors
    if not hover_only:
        return []

    examples = ", ".join(sorted(hover_only)[:MAX_EXAMPLES])
    return [_finding(
        "info",
        "Interaction relies on :hover with no touch equivalent",
        f"{page.url} defines :hover styling for {len(hover_only)} selector(s) with no "
        f"matching :focus or :active rule: {examples}. Content or affordances that only "
        "appear on hover (tooltips, dropdown menus, reveal-on-hover controls) can be "
        "effectively unreachable on a touchscreen, which has no hover state.",
        recommendation="Mirror :hover rules with :focus (keyboard) and, where the "
                        "interaction hides content, ensure a tap/click can trigger the same "
                        "state instead of relying on hover alone.",
    )]


def _declared_square_px(css_text: str) -> Optional[float]:
    raw = dict(_DECL_RE.findall(css_text or ""))
    width = _to_px(raw.get("width", ""))
    height = _to_px(raw.get("height", ""))
    if width is None or height is None:
        return None
    return min(width, height)


def _to_px(value: str) -> Optional[float]:
    match = _PX_RE.match((value or "").strip())
    return float(match.group(1)) if match else None


def _base_selector(selector: str) -> str:
    return selector.strip().split(":")[0].strip() or selector.strip()


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
