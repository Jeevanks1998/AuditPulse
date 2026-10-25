"""
Finds http:// resources on an https:// page. "Active" ones (scripts, styles,
iframes) are blocked by browsers; "passive" ones (images, media) mark the page insecure.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlparse

from crawler.parser import ParsedPage

MODULE = "security"
CATEGORY = "mixed_content"

MAX_EXAMPLES = 5

# (tag, attribute) pairs that load active content.
_ACTIVE_SOURCES = (
    ("script", "src"),
    ("link", "href"),   # stylesheets only (filtered below)
    ("iframe", "src"),
)
_PASSIVE_SOURCES = (
    ("img", "src"),
    ("video", "src"),
    ("audio", "src"),
    ("source", "src"),
)


def check_mixed_content(page: ParsedPage) -> List[dict]:
    """Findings for http:// resources referenced from an https:// page."""
    if urlparse(page.url).scheme != "https":
        return []  # only relevant on an https page

    active = _find_insecure(page, _ACTIVE_SOURCES, stylesheets_only=True)
    passive = _find_insecure(page, _PASSIVE_SOURCES, stylesheets_only=False)

    findings: List[dict] = []

    if active:
        shown = active[:MAX_EXAMPLES]
        examples = "; ".join(shown)
        more = f" (+{len(active) - MAX_EXAMPLES} more)" if len(active) > MAX_EXAMPLES else ""
        findings.append(_finding(
            "critical",
            "Active mixed content (blocked scripts/styles/frames)",
            f"{page.url} loads {len(active)} script, stylesheet, or iframe resource(s) over "
            f"plain HTTP: {examples}{more}. Modern browsers block active mixed content "
            "outright, so these resources silently fail to load — potentially breaking "
            "functionality or styling with no visible error to the user.",
            recommendation="Change these references to https://, or to protocol-relative "
                            "(//host/path) / root-relative (/path) URLs so they inherit the "
                            "page's own scheme.",
        ))

    if passive:
        shown = passive[:MAX_EXAMPLES]
        examples = "; ".join(shown)
        more = f" (+{len(passive) - MAX_EXAMPLES} more)" if len(passive) > MAX_EXAMPLES else ""
        findings.append(_finding(
            "warning",
            "Passive mixed content (insecure images/media)",
            f"{page.url} loads {len(passive)} image or media resource(s) over plain HTTP: "
            f"{examples}{more}. Browsers still render these but mark the overall page as not "
            "fully secure, and the request itself is unencrypted and tamperable in transit.",
            recommendation="Update these src attributes to https://, or root-relative URLs, "
                            "so every resource loads over the same secure connection as the "
                            "page.",
        ))

    return findings


def _find_insecure(page: ParsedPage, sources, stylesheets_only: bool) -> List[str]:
    found: List[str] = []
    for tag_name, attr in sources:
        for tag in page.soup.find_all(tag_name):
            if tag_name == "link" and stylesheets_only:
                rel = tag.get("rel") or []
                rel = [rel] if isinstance(rel, str) else rel
                if not any((r or "").lower() == "stylesheet" for r in rel):
                    continue
            value = (tag.get(attr) or "").strip()
            if value.lower().startswith("http://"):
                found.append(f"<{tag_name}> {value}")
    return found


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
