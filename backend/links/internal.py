"""
links/internal.py

Page-level checks on a page's own internal links: dead-end pages with
no internal links out at all, internal links carrying nofollow (which
blocks link equity/crawl budget from flowing between a site's own
pages — a very different concern than nofollow on an external link,
see links/external.py), and generic/non-descriptive anchor text
("click here", "read more") that tells a user or a screen reader
nothing about the destination.

Takes the crawler.links.Link list a caller already resolved for the
page (crawler.links.extract_links), the same list seo/broken_links.py
and links/external.py consume, so link resolution/classification only
happens once per page no matter how many downstream checks need it.
"""

from __future__ import annotations

from typing import List, Optional

from crawler.links import Link
from crawler.parser import ParsedPage

MODULE = "links"
CATEGORY = "internal"

_GENERIC_ANCHOR_TEXTS = {
    "click here", "here", "read more", "more", "learn more", "link",
    "this link", "this page", "continue reading", "more info", "details",
}

MIN_INTERNAL_LINKS = 1
MAX_EXAMPLES = 5


def check_internal_links(page: ParsedPage, links: List[Link]) -> List[dict]:
    """Findings for a page's own internal links: dead ends, nofollow, and generic anchor text."""
    internal = [link for link in links if link.is_internal and not link.is_asset]

    findings: List[dict] = []
    findings += _check_no_internal_links(page, internal)
    findings += _check_nofollow_internal(page, internal)
    findings += _check_generic_anchor_text(page, internal)
    return findings


def _check_no_internal_links(page: ParsedPage, internal: List[Link]) -> List[dict]:
    if len(internal) >= MIN_INTERNAL_LINKS:
        return []

    return [_finding(
        "warning",
        "Page has no internal links",
        f"{page.url} links to no other page on the same site. A visitor arriving here has "
        "no way to continue browsing except the browser back button, and crawlers have no "
        "path from this page to the rest of the site.",
        recommendation="Add navigation, related-content, or breadcrumb links so the page "
                        "connects to the rest of the site.",
    )]


def _check_nofollow_internal(page: ParsedPage, internal: List[Link]) -> List[dict]:
    nofollowed = [link for link in internal if link.nofollow]
    if not nofollowed:
        return []

    examples = ", ".join(link.url for link in nofollowed[:MAX_EXAMPLES])
    return [_finding(
        "warning",
        "Internal links marked nofollow",
        f"{page.url} has {len(nofollowed)} internal link(s) with rel=\"nofollow\": "
        f"{examples}. nofollow on an internal link blocks link equity and crawl priority "
        "from flowing to a page on your own site — almost never intentional, unlike "
        "nofollow on an external link.",
        recommendation="Remove rel=\"nofollow\" from internal links unless the destination "
                        "is genuinely meant to be de-prioritized (e.g. a login or admin "
                        "page you don't want indexed).",
    )]


def _check_generic_anchor_text(page: ParsedPage, internal: List[Link]) -> List[dict]:
    generic = [link for link in internal if link.text.strip().lower() in _GENERIC_ANCHOR_TEXTS]
    if not generic:
        return []

    examples = ", ".join(f"\"{link.text.strip()}\" → {link.url}" for link in generic[:MAX_EXAMPLES])
    return [_finding(
        "info",
        "Generic anchor text on internal links",
        f"{page.url} has {len(generic)} internal link(s) with non-descriptive anchor text: "
        f"{examples}. Screen reader users often navigate by pulling a list of links out of "
        "context, and generic text like \"click here\" gives no clue where any of them go; "
        "it also gives search engines nothing to associate with the destination page.",
        recommendation="Use anchor text that describes the destination (e.g. \"View "
                        "pricing plans\" instead of \"Click here\").",
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
