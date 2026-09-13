"""
forms/required_fields.py

Checks that `required` (and its visual signal, usually an asterisk or
the word "required" in the label) agree with each other. This is
distinct from accessibility/labels.py, which checks whether a control
has *any* accessible name at all — this assumes a label exists and
asks whether it accurately represents whether the field is mandatory,
in both directions: a required field a sighted user has no visual cue
about, and a field visually marked required that isn't actually
enforced.
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "forms"
CATEGORY = "required"

_REQUIRED_MARKER_RE = re.compile(r"\*|\brequired\b", re.IGNORECASE)
LABEL_EXEMPT_INPUT_TYPES = {"hidden", "submit", "button", "image", "reset", "checkbox", "radio"}
MAX_EXAMPLES = 5


def check_required_fields(page: ParsedPage) -> List[dict]:
    """Findings for mismatches between the `required` attribute and its visual indicator."""
    forms = page.soup.find_all("form")
    if not forms:
        return []

    soup = page.soup
    labeled_for_ids = {tag.get("for"): tag for tag in soup.find_all("label", attrs={"for": True})}

    findings: List[dict] = []
    findings += _check_required_without_visual_cue(page, forms, labeled_for_ids)
    findings += _check_visual_cue_without_required(page, forms, labeled_for_ids)
    return findings


def _check_required_without_visual_cue(page: ParsedPage, forms: list, labeled_for_ids: dict) -> List[dict]:
    missing_cue = []
    for form in forms:
        for tag in form.find_all(["input", "select", "textarea"]):
            if tag.get("required") is None and tag.get("aria-required", "").lower() != "true":
                continue
            if tag.name == "input" and (tag.get("type") or "text").lower() in LABEL_EXEMPT_INPUT_TYPES:
                continue
            label = _associated_label_text(tag, labeled_for_ids)
            if label and _REQUIRED_MARKER_RE.search(label):
                continue
            missing_cue.append(tag.get("name") or tag.get("id") or f"<{tag.name}>")

    if not missing_cue:
        return []

    examples = ", ".join(missing_cue[:MAX_EXAMPLES])
    return [_finding(
        "info",
        "Required field has no visible required indicator",
        f"{page.url} has {len(missing_cue)} required field(s) whose label has no asterisk "
        f"or \"required\" text: {examples}. A sighted user filling out the form has no way "
        "to tell it's mandatory until they try to submit and get an error.",
        recommendation="Mark required fields visually (an asterisk plus a legend explaining "
                        "what it means, or the word \"required\" in the label) in addition to "
                        "the required attribute.",
    )]


def _check_visual_cue_without_required(page: ParsedPage, forms: list, labeled_for_ids: dict) -> List[dict]:
    missing_attr = []
    for form in forms:
        for tag in form.find_all(["input", "select", "textarea"]):
            if tag.name == "input" and (tag.get("type") or "text").lower() in LABEL_EXEMPT_INPUT_TYPES:
                continue
            label = _associated_label_text(tag, labeled_for_ids)
            if not (label and _REQUIRED_MARKER_RE.search(label)):
                continue
            if tag.get("required") is not None or tag.get("aria-required", "").lower() == "true":
                continue
            missing_attr.append(tag.get("name") or tag.get("id") or f"<{tag.name}>")

    if not missing_attr:
        return []

    examples = ", ".join(missing_attr[:MAX_EXAMPLES])
    return [_finding(
        "warning",
        "Field marked required in its label isn't enforced",
        f"{page.url} has {len(missing_attr)} field(s) whose label indicates it's required "
        f"(asterisk or \"required\" text) but that carry neither a required attribute nor "
        f"aria-required=\"true\": {examples}. The form can be submitted with these left "
        "blank despite telling the user otherwise.",
        recommendation="Add the required attribute (or aria-required=\"true\" for a "
                        "custom-validated field) so enforcement matches what the label "
                        "promises.",
    )]


def _associated_label_text(tag, labeled_for_ids: dict) -> Optional[str]:
    tag_id = tag.get("id")
    if tag_id and tag_id in labeled_for_ids:
        return labeled_for_ids[tag_id].get_text(strip=True)
    parent_label = tag.find_parent("label")
    if parent_label is not None:
        return parent_label.get_text(strip=True)
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
