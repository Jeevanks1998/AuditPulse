"""
forms/autocomplete.py

Checks the `autocomplete` attribute against the WHATWG-defined tokens
browsers and password managers actually recognize (email, tel, given-
name, cc-number, etc.), for two failure modes: a common field with no
autocomplete attribute at all, and a password field explicitly opted
out via autocomplete="off" — a pattern browsers now largely ignore for
login forms anyway, but which still suppresses password-manager
save/fill prompts in some contexts and offers no real security benefit.
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "forms"
CATEGORY = "autocomplete"

# field identity substring -> expected autocomplete token(s)
_FIELD_AUTOCOMPLETE_HINTS = [
    (re.compile(r"e-?mail", re.IGNORECASE), {"email"}),
    (re.compile(r"first.?name|given.?name|fname", re.IGNORECASE), {"given-name"}),
    (re.compile(r"last.?name|surname|family.?name|lname", re.IGNORECASE), {"family-name"}),
    (re.compile(r"phone|tel(ephone)?|mobile", re.IGNORECASE), {"tel"}),
    (re.compile(r"zip|postal", re.IGNORECASE), {"postal-code"}),
    (re.compile(r"card.?number|cc.?number", re.IGNORECASE), {"cc-number"}),
    (re.compile(r"card.?name|cc.?name|name.?on.?card", re.IGNORECASE), {"cc-name"}),
    (re.compile(r"\bcvv\b|\bcvc\b|security.?code", re.IGNORECASE), {"cc-csc"}),
    (re.compile(r"expir|cc.?exp", re.IGNORECASE), {"cc-exp", "cc-exp-month", "cc-exp-year"}),
]

MAX_EXAMPLES = 5


def check_autocomplete(page: ParsedPage) -> List[dict]:
    """Findings for missing autocomplete on common fields and disabled autocomplete on passwords."""
    forms = page.soup.find_all("form")
    if not forms:
        return []

    findings: List[dict] = []
    findings += _check_missing_autocomplete(page, forms)
    findings += _check_password_autocomplete(page, forms)
    return findings


def _check_missing_autocomplete(page: ParsedPage, forms: list) -> List[dict]:
    missing = []
    for form in forms:
        for tag in form.find_all("input"):
            existing = (tag.get("autocomplete") or "").strip().lower()
            if existing and existing != "off":
                continue
            identity = " ".join(filter(None, [tag.get("name"), tag.get("id"), tag.get("placeholder")]))
            for pattern, expected_tokens in _FIELD_AUTOCOMPLETE_HINTS:
                if pattern.search(identity):
                    label = tag.get("name") or tag.get("id") or "<input>"
                    missing.append((label, sorted(expected_tokens)[0]))
                    break

    if not missing:
        return []

    examples = ", ".join(f"{name} → autocomplete=\"{token}\"" for name, token in missing[:MAX_EXAMPLES])
    return [_finding(
        "info",
        "Common field missing an autocomplete attribute",
        f"{page.url} has {len(missing)} field(s) that look like a standard identity/contact/"
        f"payment field but have no matching autocomplete attribute: {examples}. Without it, "
        "browsers and password managers can't reliably offer to fill the field, costing "
        "users time on every visit.",
        recommendation="Set autocomplete to the matching WHATWG token (email, tel, "
                        "given-name, cc-number, etc.) for standard identity, contact, and "
                        "payment fields.",
    )]


def _check_password_autocomplete(page: ParsedPage, forms: list) -> List[dict]:
    disabled = []
    for form in forms:
        for tag in form.find_all("input", attrs={"type": "password"}):
            if (tag.get("autocomplete") or "").strip().lower() == "off":
                disabled.append(tag.get("name") or tag.get("id") or "<input type=\"password\">")

    if not disabled:
        return []

    examples = ", ".join(disabled[:MAX_EXAMPLES])
    return [_finding(
        "info",
        "Password field disables autocomplete",
        f"{page.url} has {len(disabled)} password field(s) with autocomplete=\"off\": "
        f"{examples}. Most modern browsers ignore this on login/password fields anyway, but "
        "it still isn't a security control and can interfere with password-manager save/fill "
        "prompts in some contexts.",
        recommendation="Use autocomplete=\"current-password\" on login forms or "
                        "autocomplete=\"new-password\" on signup/change-password forms "
                        "instead of \"off\".",
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
