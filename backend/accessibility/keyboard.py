"""
accessibility/keyboard.py

Static keyboard-operability checks (WCAG 2.1.1 "Keyboard", 2.4.1
"Bypass Blocks", 2.4.3 "Focus Order"): positive tabindex values that
fight the browser's natural DOM-order tab sequence, click handlers on
non-interactive elements with no keyboard equivalent, duplicate
accesskey values, and a missing skip-to-content link. All of this is
visible in static markup, so no rendering/JS execution is needed —
what we can't see (custom JS keydown handling that does compensate for
a div-with-onclick, for instance) is exactly what accessibility/axe.py
and accessibility/pa11y.py's rendered runs catch instead.
"""

from __future__ import annotations

from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "accessibility"
CATEGORY = "keyboard"

NATIVELY_INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "label", "summary"}
NON_INTERACTIVE_CLICKABLE_TAGS = {"div", "span", "li", "td", "tr", "p", "img", "section"}

MAX_EXAMPLES = 5


def check_keyboard(page: ParsedPage) -> List[dict]:
    """Findings for keyboard operability issues on one page."""
    soup = page.soup
    findings: List[dict] = []

    findings += _check_positive_tabindex(page, soup)
    findings += _check_unreachable_click_handlers(page, soup)
    findings += _check_duplicate_accesskeys(page, soup)
    findings += _check_skip_link(page, soup)

    return findings


def _check_positive_tabindex(page: ParsedPage, soup) -> List[dict]:
    offenders = []
    for tag in soup.find_all(attrs={"tabindex": True}):
        try:
            value = int(tag["tabindex"])
        except (ValueError, TypeError):
            continue
        if value > 0:
            offenders.append((tag.name, value))

    if not offenders:
        return []
    examples = ", ".join(f"<{n} tabindex=\"{v}\">" for n, v in offenders[:MAX_EXAMPLES])
    return [_finding(
        "warning",
        "Positive tabindex overrides natural tab order",
        f"{page.url} has {len(offenders)} element(s) with a positive tabindex, e.g. "
        f"{examples}. Positive values pull those elements to the front of the tab sequence "
        "ahead of everything else, regardless of visual layout — a frequent source of "
        "confusing, hard-to-predict keyboard navigation.",
        recommendation="Use tabindex=\"0\" (join the natural order) or reorder the underlying "
                        "markup instead of positive tabindex values.",
    )]


def _check_unreachable_click_handlers(page: ParsedPage, soup) -> List[dict]:
    offenders = []
    for tag_name in NON_INTERACTIVE_CLICKABLE_TAGS:
        for tag in soup.find_all(tag_name, attrs={"onclick": True}):
            has_role = (tag.get("role") or "").strip().lower() in (
                "button", "link", "menuitem", "tab", "checkbox", "switch", "option",
            )
            has_tabindex = tag.has_attr("tabindex")
            if not (has_role and has_tabindex):
                offenders.append(tag.name)

    if not offenders:
        return []
    return [_finding(
        "critical",
        "Click handler on a non-interactive, non-focusable element",
        f"{page.url} has {len(offenders)} element(s) (e.g. <{offenders[0]}>) with an onclick "
        "handler but no interactive role and no tabindex, so a keyboard-only user can never "
        "focus or activate it — the functionality is mouse/touch-only.",
        recommendation="Use a real <button> or <a href> instead, or if that's not possible "
                        "add role=\"button\" (or the appropriate role), tabindex=\"0\", and a "
                        "keydown handler for Enter/Space.",
    )]


def _check_duplicate_accesskeys(page: ParsedPage, soup) -> List[dict]:
    seen: dict = {}
    for tag in soup.find_all(attrs={"accesskey": True}):
        key = (tag.get("accesskey") or "").strip().lower()
        if not key:
            continue
        seen.setdefault(key, 0)
        seen[key] += 1

    duplicated = {k: v for k, v in seen.items() if v > 1}
    if not duplicated:
        return []
    examples = ", ".join(f'"{k}" ({v}x)' for k, v in list(duplicated.items())[:MAX_EXAMPLES])
    return [_finding(
        "warning",
        "Duplicate accesskey values",
        f"{page.url} assigns the same accesskey to more than one element: {examples}. "
        "Browsers resolve duplicate accesskeys inconsistently, so only one target is "
        "reliably reachable.",
        recommendation="Make every accesskey value unique on the page, or remove accesskey "
                        "entirely and rely on standard tab navigation.",
    )]


def _check_skip_link(page: ParsedPage, soup) -> List[dict]:
    body = soup.find("body")
    if body is None:
        return []

    anchors = soup.find_all("a", href=True)
    has_skip_link = any(
        _looks_like_skip_link(a) for a in anchors[:10]  # a real skip link is always near the top
    )
    if has_skip_link:
        return []

    # Only worth flagging on pages substantial enough for repeated nav to be a real burden.
    nav_landmarks = soup.find_all(["nav"]) + soup.find_all(attrs={"role": "navigation"})
    if not nav_landmarks:
        return []

    return [_finding(
        "info",
        "No skip-to-content link",
        f"{page.url} has navigation but no \"skip to content\" link at the top of the page. "
        "Without one, keyboard users must tab through the entire nav on every single page "
        "load before reaching the main content.",
        recommendation="Add a visually-hidden-until-focused link as the first focusable "
                        "element, e.g. <a href=\"#main\">Skip to content</a>, targeting the "
                        "main content region's id.",
    )]


def _looks_like_skip_link(tag) -> bool:
    href = (tag.get("href") or "").strip()
    text = tag.get_text(strip=True).lower()
    return href.startswith("#") and ("skip" in text and ("content" in text or "main" in text))


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
