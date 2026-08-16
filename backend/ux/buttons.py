"""
ux/buttons.py

Checks on clickable calls-to-action: <button> elements, <input
type="submit"/"button">, and anchors styled to look like buttons (class
containing "btn"/"button"). Two concerns:

  - Label clarity: generic text ("click here", "submit", "learn more")
    forces visitors to read surrounding context to know what a button
    actually does, and is worse for anyone scanning quickly or
    navigating by a screen reader's "list all buttons" shortcut.
  - A correctness footgun: <button> with no explicit `type` defaults to
    type="submit", so a button meant to just toggle a menu or open a
    modal can accidentally submit an enclosing <form> if one is ever
    added around it later.

Reads crawler.parser.ParsedPage.soup directly since button styling
classes and the accessible-name computation both need the live tag
tree, not the flat fields ParsedPage extracts.
"""

from __future__ import annotations

from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "ux"
CATEGORY = "buttons"

MAX_EXAMPLES = 5

_GENERIC_LABELS = {
    "click here", "here", "click", "submit", "go", "ok", "read more",
    "more", "learn more", "link", "button",
}


def check_buttons(page: ParsedPage) -> List[dict]:
    """Findings for unclear button labels and missing explicit button type."""
    buttons = _collect_buttons(page)
    if not buttons:
        return []

    findings: List[dict] = []
    findings += _check_generic_labels(page, buttons)
    findings += _check_missing_type(page)
    return findings


def _collect_buttons(page: ParsedPage):
    tags = list(page.soup.find_all("button"))
    tags += page.soup.find_all("input", attrs={"type": lambda v: (v or "").lower() in ("submit", "button")})
    tags += [
        a for a in page.anchor_tags
        if _has_button_class(a)
    ]
    return tags


def _has_button_class(tag) -> bool:
    classes = tag.get("class") or []
    classes = [classes] if isinstance(classes, str) else classes
    return any("btn" in c.lower() or "button" in c.lower() for c in classes)


def _accessible_label(tag) -> str:
    if tag.name == "input":
        return (tag.get("value") or tag.get("aria-label") or "").strip()
    aria_label = (tag.get("aria-label") or "").strip()
    if aria_label:
        return aria_label
    return tag.get_text(strip=True)


def _check_generic_labels(page: ParsedPage, buttons) -> List[dict]:
    generic = []
    empty = 0
    for tag in buttons:
        label = _accessible_label(tag)
        if not label:
            empty += 1
        elif label.strip().lower().rstrip(".!") in _GENERIC_LABELS:
            generic.append(label)

    findings: List[dict] = []

    if empty:
        findings.append(_finding(
            "warning",
            "Button(s) with no visible or accessible label",
            f"{page.url} has {empty} button-like element(s) with no text content, value, or "
            "aria-label. Visitors — and especially screen reader users, who hear nothing at "
            "all announced — have no way to know what the control does.",
            recommendation="Give every button real visible text describing its action, or an "
                            "aria-label if it's icon-only.",
        ))

    if generic:
        shown = generic[:MAX_EXAMPLES]
        return findings + [_finding(
            "info",
            "Generic button labels",
            f"{page.url} has {len(generic)} button(s) labeled with generic text like "
            f"{', '.join(repr(g) for g in shown)}. Labels like \"click here\" or \"submit\" "
            "don't say what will happen, which matters most for visitors scanning the page "
            "quickly or navigating via a screen reader's button-list shortcut, where buttons "
            "are heard out of their surrounding context.",
            recommendation="Use action-specific labels that describe the outcome — "
                            "\"Download report\" or \"Create account\" rather than \"Click "
                            "here\" or \"Submit\".",
        )]

    return findings


def _check_missing_type(page: ParsedPage) -> List[dict]:
    buttons_in_forms = [
        b for form in page.soup.find_all("form") for b in form.find_all("button")
    ]
    missing_type = [b for b in buttons_in_forms if not b.get("type")]
    if not missing_type:
        return []

    return [_finding(
        "info",
        "Button inside a form has no explicit type",
        f"{page.url} has {len(missing_type)} <button> element(s) inside a <form> with no "
        "`type` attribute. A <button> defaults to type=\"submit\" — if any of these are "
        "meant to just toggle something (a menu, a password-visibility icon, etc.) rather "
        "than submit the form, they'll do so unintentionally.",
        recommendation="Add an explicit `type=\"button\"` to any <button> inside a form "
                        "that isn't meant to submit it, and `type=\"submit\"` to the one "
                        "that is, so intent doesn't depend on browser defaults.",
    )]


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
