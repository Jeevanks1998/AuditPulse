"""
accessibility/labels.py

Accessible-name checks (WCAG 4.1.2 "Name, Role, Value") for form
controls, buttons, and links: an input with no associated <label> (or
aria-label/aria-labelledby/title fallback), a button or link with no
text a screen reader can announce, and grouped radio/checkbox inputs
with no <fieldset>/<legend> explaining what the group means as a
whole. Reads crawler.parser.ParsedPage.soup directly for form markup
that isn't part of ParsedPage's normal extracted fields.
"""

from __future__ import annotations

from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "accessibility"
CATEGORY = "labels"

# input types that don't need a visible/associated label of their own
# (submit/button/image/hidden carry their own text or aren't perceivable controls;
# reset is borderline but conventionally exempted the same way).
LABEL_EXEMPT_INPUT_TYPES = {"hidden", "submit", "button", "image", "reset"}

MAX_EXAMPLES = 5


def check_labels(page: ParsedPage) -> List[dict]:
    """Findings for missing accessible names on this page's controls."""
    soup = page.soup
    findings: List[dict] = []

    findings += _check_unlabeled_inputs(page, soup)
    findings += _check_unnamed_buttons_and_links(page, soup)
    findings += _check_ungrouped_radio_checkbox(page, soup)

    return findings


def _check_unlabeled_inputs(page: ParsedPage, soup) -> List[dict]:
    labeled_for_ids = {tag.get("for") for tag in soup.find_all("label", attrs={"for": True})}
    unlabeled = []

    controls = soup.find_all("input") + soup.find_all("select") + soup.find_all("textarea")
    for control in controls:
        if control.name == "input" and (control.get("type") or "text").lower() in LABEL_EXEMPT_INPUT_TYPES:
            continue
        if _has_accessible_name(control, labeled_for_ids):
            continue
        unlabeled.append(control.get("name") or control.get("id") or f"<{control.name}>")

    if not unlabeled:
        return []
    examples = ", ".join(str(u) for u in unlabeled[:MAX_EXAMPLES])
    return [_finding(
        "critical",
        "Form control missing an accessible label",
        f"{page.url} has {len(unlabeled)} form control(s) with no associated <label>, "
        f"aria-label, aria-labelledby, or title: {examples}. Screen reader users hear only "
        "\"edit text\" or similar with no indication of what to enter.",
        recommendation="Add a <label for=\"...\"> matching the control's id (or wrap the "
                        "control in a <label>), or use aria-label/aria-labelledby if a "
                        "visible label isn't appropriate.",
    )]


def _has_accessible_name(control, labeled_for_ids: set) -> bool:
    if control.get("id") in labeled_for_ids and control.get("id"):
        return True
    if control.get("aria-label") and control["aria-label"].strip():
        return True
    if control.get("aria-labelledby"):
        return True
    if control.get("title") and control["title"].strip():
        return True
    # <label>...<input>...</label> wrapping, without a for/id pair
    parent = control.find_parent("label")
    if parent is not None:
        return True
    return False


def _check_unnamed_buttons_and_links(page: ParsedPage, soup) -> List[dict]:
    offenders = []

    for tag in soup.find_all("button"):
        if not _accessible_text(tag):
            offenders.append("<button>")

    for tag in soup.find_all("a", href=True):
        if not _accessible_text(tag):
            offenders.append("<a>")

    for tag in soup.find_all("input", attrs={"type": ["submit", "button", "image"]}):
        label = tag.get("value") or tag.get("alt") or tag.get("aria-label")
        if not (label and label.strip()):
            offenders.append(f"<input type=\"{tag.get('type')}\">")

    if not offenders:
        return []
    return [_finding(
        "critical",
        "Button or link has no accessible text",
        f"{page.url} has {len(offenders)} interactive element(s) with no text content, "
        "aria-label, or (for images inside) alt text a screen reader can announce — e.g. "
        f"{offenders[0]}. It's reachable by keyboard but announced as empty, giving no clue "
        "what it does.",
        recommendation="Add visible text, an aria-label, or (for icon-only controls) a "
                        "visually-hidden text node describing the action.",
    )]


def _accessible_text(tag) -> bool:
    if tag.get_text(strip=True):
        return True
    if tag.get("aria-label") and tag["aria-label"].strip():
        return True
    if tag.get("aria-labelledby"):
        return True
    for img in tag.find_all("img"):
        if (img.get("alt") or "").strip():
            return True
    return False


def _check_ungrouped_radio_checkbox(page: ParsedPage, soup) -> List[dict]:
    groups: dict = {}
    for tag in soup.find_all("input", attrs={"type": ["radio", "checkbox"]}):
        name = tag.get("name")
        if not name:
            continue
        groups.setdefault(name, []).append(tag)

    ungrouped_names = []
    for name, inputs in groups.items():
        if len(inputs) < 2:
            continue  # a lone checkbox doesn't need a fieldset, just its own label
        has_fieldset = any(inp.find_parent("fieldset") is not None for inp in inputs)
        has_legend = has_fieldset and any(
            (inp.find_parent("fieldset") or {}).find("legend") for inp in inputs
        ) if has_fieldset else False
        if not (has_fieldset and has_legend):
            ungrouped_names.append(name)

    if not ungrouped_names:
        return []
    examples = ", ".join(ungrouped_names[:MAX_EXAMPLES])
    return [_finding(
        "warning",
        "Radio/checkbox group missing fieldset and legend",
        f"{page.url} has {len(ungrouped_names)} multi-option radio/checkbox group(s) not "
        f"wrapped in a <fieldset> with a <legend>: {examples}. Each option has its own label, "
        "but nothing announces what the group as a whole is asking.",
        recommendation="Wrap each related set of radio buttons or checkboxes in "
                        "<fieldset><legend>Question or group name</legend>...</fieldset>.",
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
