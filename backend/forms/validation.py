"""
forms/validation.py

Checks whether inputs use a validation-aware `type` and the attributes
that go with it (pattern, min/max/step) instead of falling back to
type="text" for everything, which gets a user no built-in keyboard
hinting, no format checking, and no error messaging from the browser
at all. Reads crawler.parser.ParsedPage.soup directly for <form>/
<input> markup, the same declared-markup approach accessibility/
labels.py uses for the same tags.
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "forms"
CATEGORY = "validation"

# name/id/placeholder substrings that strongly suggest a field's intended
# semantic type even though the markup uses a generic type="text".
_TYPE_HINTS = {
    "email": re.compile(r"e-?mail", re.IGNORECASE),
    "tel": re.compile(r"phone|tel(ephone)?|mobile", re.IGNORECASE),
    "url": re.compile(r"\burl\b|website", re.IGNORECASE),
}

NUMBER_TYPES = {"number", "range"}
MAX_EXAMPLES = 5


def check_validation(page: ParsedPage) -> List[dict]:
    """Findings for generic-typed inputs and numeric inputs missing min/max/step."""
    forms = page.soup.find_all("form")
    if not forms:
        return []

    findings: List[dict] = []
    findings += _check_generic_typed_inputs(page, forms)
    findings += _check_number_bounds(page, forms)
    findings += _check_no_validation_at_all(page, forms)
    return findings


def _check_generic_typed_inputs(page: ParsedPage, forms: list) -> List[dict]:
    mistyped = []
    for form in forms:
        for tag in form.find_all("input"):
            input_type = (tag.get("type") or "text").lower()
            if input_type != "text":
                continue
            identity = " ".join(filter(None, [tag.get("name"), tag.get("id"), tag.get("placeholder")]))
            for suggested_type, pattern in _TYPE_HINTS.items():
                if pattern.search(identity):
                    mistyped.append((tag.get("name") or tag.get("id") or "<input>", suggested_type))
                    break

    if not mistyped:
        return []

    examples = ", ".join(f"{name} → type=\"{t}\"" for name, t in mistyped[:MAX_EXAMPLES])
    return [_finding(
        "info",
        "Input uses type=\"text\" for a more specific field",
        f"{page.url} has {len(mistyped)} field(s) whose name/id/placeholder suggest a "
        f"specific data type but that use type=\"text\": {examples}. type=\"text\" gets none "
        "of the matching mobile keyboard, built-in format validation, or autofill hinting "
        "the more specific type provides.",
        recommendation="Use the semantic input type (email, tel, url, number, date, etc.) "
                        "that matches what the field actually collects.",
    )]


def _check_number_bounds(page: ParsedPage, forms: list) -> List[dict]:
    unbounded = []
    for form in forms:
        for tag in form.find_all("input", attrs={"type": list(NUMBER_TYPES)}):
            if tag.get("min") is None and tag.get("max") is None:
                unbounded.append(tag.get("name") or tag.get("id") or f"<input type=\"{tag.get('type')}\">")

    if not unbounded:
        return []

    examples = ", ".join(unbounded[:MAX_EXAMPLES])
    return [_finding(
        "info",
        "Numeric input has no min/max bounds",
        f"{page.url} has {len(unbounded)} number/range input(s) with neither min nor max "
        f"set: {examples}. Without bounds the browser can't reject obviously invalid values "
        "(negative quantities, out-of-range ages, etc.) before the form is submitted.",
        recommendation="Set min and/or max (and step, where relevant) to the field's valid "
                        "range so the browser catches invalid values immediately.",
    )]


def _check_no_validation_at_all(page: ParsedPage, forms: list) -> List[dict]:
    unvalidated_forms = 0
    for form in forms:
        text_like_inputs = form.find_all(
            "input", attrs={"type": ["text", "email", "tel", "url", "password", "number", None]}
        )
        if not text_like_inputs:
            continue
        has_any_validation = any(
            tag.get("required") is not None
            or tag.get("pattern")
            or tag.get("minlength")
            or tag.get("maxlength")
            or (tag.get("type") or "text").lower() in ("email", "url", "tel", "number")
            for tag in text_like_inputs
        )
        if not has_any_validation:
            unvalidated_forms += 1

    if not unvalidated_forms:
        return []

    return [_finding(
        "warning",
        "Form has no client-side validation",
        f"{page.url} has {unvalidated_forms} form(s) where none of the text-like inputs "
        "carry required, pattern, minlength/maxlength, or a validating type (email/url/tel/"
        "number). Every field will submit as-is regardless of content, pushing all "
        "validation work — and round-trips for the user — onto the server.",
        recommendation="Add required attributes and appropriate types/patterns for fields "
                        "that need them, while still validating on the server as the "
                        "authoritative check.",
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
