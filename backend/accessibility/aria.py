"""
accessibility/aria.py

Static ARIA checks that only need the parsed DOM, no rendering: invalid
`role` values, `aria-*` attributes referencing an `id` that doesn't
exist anywhere on the page, `aria-hidden="true"` on an element that's
still keyboard-focusable (screen reader users can't perceive it, but
sighted keyboard users can still tab to an invisible-to-AT control —
a classic WCAG 4.1.2 failure), and redundant roles that just restate an
element's implicit native role. Reads crawler.parser.ParsedPage.soup
directly since none of this is pulled into ParsedPage's normal fields.
"""

from __future__ import annotations

from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "accessibility"
CATEGORY = "aria"

# WAI-ARIA 1.2 role list (abstract roles excluded — those are never
# valid as an author-supplied role="..." value).
VALID_ROLES = {
    "alert", "alertdialog", "application", "article", "banner", "button",
    "cell", "checkbox", "columnheader", "combobox", "complementary",
    "contentinfo", "definition", "dialog", "directory", "document",
    "feed", "figure", "form", "grid", "gridcell", "group", "heading",
    "img", "link", "list", "listbox", "listitem", "log", "main",
    "marquee", "math", "menu", "menubar", "menuitem", "menuitemcheckbox",
    "menuitemradio", "navigation", "none", "note", "option", "presentation",
    "progressbar", "radio", "radiogroup", "region", "row", "rowgroup",
    "rowheader", "scrollbar", "search", "searchbox", "separator",
    "slider", "spinbutton", "status", "switch", "tab", "table",
    "tablist", "tabpanel", "term", "textbox", "timer", "toolbar",
    "tooltip", "tree", "treegrid", "treeitem",
}

# Attributes whose value is expected to be one or more element `id`s.
ID_REFERENCE_ATTRS = ("aria-labelledby", "aria-describedby", "aria-controls", "aria-owns", "aria-activedescendant")

FOCUSABLE_SELECTORS = ("a[href]", "button", "input", "select", "textarea", "[tabindex]")

# Native tag -> the role it already implies; role="..." repeating this adds nothing.
REDUNDANT_ROLE_FOR_TAG = {
    "button": "button", "a": "link", "nav": "navigation", "main": "main",
    "header": "banner", "footer": "contentinfo", "form": "form",
    "table": "table", "ul": "list", "ol": "list", "li": "listitem",
    "img": "img", "aside": "complementary", "article": "article",
}

MAX_EXAMPLES = 5


def check_aria(page: ParsedPage) -> List[dict]:
    """Findings for ARIA role/attribute misuse on one page."""
    soup = page.soup
    findings: List[dict] = []

    all_ids = {tag.get("id") for tag in soup.find_all(id=True) if tag.get("id")}

    findings += _check_invalid_roles(page, soup)
    findings += _check_dangling_id_refs(page, soup, all_ids)
    findings += _check_aria_hidden_focusable(page, soup)
    findings += _check_redundant_roles(page, soup)

    return findings


def _check_invalid_roles(page: ParsedPage, soup) -> List[dict]:
    bad = []
    for tag in soup.find_all(attrs={"role": True}):
        role = (tag.get("role") or "").strip().lower()
        # role can be a space-separated fallback list per the ARIA spec
        tokens = [t for t in role.split() if t]
        if tokens and not any(t in VALID_ROLES for t in tokens):
            bad.append((tag.name, role))

    if not bad:
        return []
    examples = ", ".join(f'role="{r}" on <{n}>' for n, r in bad[:MAX_EXAMPLES])
    return [_finding(
        "warning",
        "Invalid ARIA role",
        f"{page.url} has {len(bad)} element(s) with a role value that isn't a real WAI-ARIA "
        f"role, e.g. {examples}. Assistive tech falls back to treating the element as having "
        "no role at all, silently dropping any semantics the role was meant to convey.",
        recommendation="Use a valid ARIA role from the WAI-ARIA spec, or remove the role "
                        "attribute and rely on the element's native semantics.",
    )]


def _check_dangling_id_refs(page: ParsedPage, soup, all_ids: set) -> List[dict]:
    dangling = []
    for tag in soup.find_all(lambda t: any(t.has_attr(a) for a in ID_REFERENCE_ATTRS)):
        for attr in ID_REFERENCE_ATTRS:
            if not tag.has_attr(attr):
                continue
            for ref_id in (tag.get(attr) or "").split():
                if ref_id not in all_ids:
                    dangling.append((tag.name, attr, ref_id))

    if not dangling:
        return []
    examples = ", ".join(f'{attr}="{ref}"' for _, attr, ref in dangling[:MAX_EXAMPLES])
    return [_finding(
        "warning",
        "ARIA attribute references a missing element id",
        f"{page.url} has {len(dangling)} ARIA id-reference(s) pointing at an id that doesn't "
        f"exist on the page, e.g. {examples}. Screen readers can't resolve the reference, so "
        "the labeling/relationship it was meant to provide silently disappears.",
        recommendation="Fix the id typo, or add the missing element — every aria-labelledby/"
                        "describedby/controls/owns/activedescendant value must match a real id.",
    )]


def _check_aria_hidden_focusable(page: ParsedPage, soup) -> List[dict]:
    offenders = []
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        if _is_focusable(tag):
            offenders.append(tag.name)

    if not offenders:
        return []
    return [_finding(
        "critical",
        "aria-hidden on a focusable element",
        f"{page.url} has {len(offenders)} element(s) that are aria-hidden=\"true\" but still "
        "keyboard-focusable (a link, button, form control, or explicit tabindex). Keyboard "
        "users can tab into a control that screen readers are told doesn't exist, landing on "
        "an announced-as-nothing focus stop.",
        recommendation="Either remove aria-hidden from the element, or also make it "
                        "non-focusable (tabindex=\"-1\", or add the `inert` attribute/`hidden` "
                        "to the containing region) so hidden and focusable stay in sync.",
    )]


def _check_redundant_roles(page: ParsedPage, soup) -> List[dict]:
    redundant = []
    for tag_name, implicit_role in REDUNDANT_ROLE_FOR_TAG.items():
        for tag in soup.find_all(tag_name, attrs={"role": implicit_role}):
            redundant.append(tag_name)

    if not redundant:
        return []
    return [_finding(
        "info",
        "Redundant ARIA role",
        f"{page.url} has {len(redundant)} element(s) with a role attribute that just restates "
        "the element's own native role (e.g. role=\"button\" on a <button>), which adds "
        "nothing and is one more place for markup to drift out of sync.",
        recommendation="Remove the redundant role attribute and rely on the element's native "
                        "semantics.",
    )]


def _is_focusable(tag) -> bool:
    if tag.name in ("a",) and tag.get("href") is not None:
        return True
    if tag.name in ("button", "input", "select", "textarea"):
        return not tag.has_attr("disabled")
    if tag.has_attr("tabindex"):
        try:
            return int(tag["tabindex"]) >= 0
        except ValueError:
            return False
    return False


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
