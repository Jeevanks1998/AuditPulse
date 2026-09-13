"""
ux/navigation.py

Page-level checks on how easy the page is to move around and orient
within: a real <nav> landmark, a sane number of primary nav links (too
few and there's nowhere to go; too many and every link competes for
attention), a way back to the homepage, and — on deeper pages —
breadcrumbs so visitors know where they are in the site's structure.
This is a UX/wayfinding lens rather than screen-reader semantics —
accessibility/aria.py and accessibility/labels.py already cover the
assistive-tech side of navigation landmarks and link names.

Reads crawler.parser.ParsedPage.soup directly since nav structure
(which links live inside <nav>, sibling ordering) isn't part of the
flat fields ParsedPage already extracts.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlparse

from crawler.parser import ParsedPage

MODULE = "ux"
CATEGORY = "navigation"

MIN_PRIMARY_LINKS = 2
MAX_PRIMARY_LINKS = 10


def check_navigation(page: ParsedPage) -> List[dict]:
    """Findings for navigation-structure and wayfinding issues."""
    findings: List[dict] = []

    nav_tags = page.soup.find_all("nav")
    findings += _check_nav_landmark(page, nav_tags)

    if nav_tags:
        findings += _check_primary_link_count(page, nav_tags)

    findings += _check_home_link(page)
    findings += _check_breadcrumbs(page)

    return findings


def _check_nav_landmark(page: ParsedPage, nav_tags) -> List[dict]:
    if nav_tags:
        return []

    # A role="navigation" div is functionally equivalent even without a <nav> tag.
    if page.soup.find(attrs={"role": "navigation"}):
        return []

    if len(page.anchor_tags) < 3:
        return []  # too few links for "no nav landmark" to mean much (e.g. a landing page)

    return [_finding(
        "warning",
        "No navigation landmark found",
        f"{page.url} has {len(page.anchor_tags)} links but no <nav> element or "
        "role=\"navigation\" container grouping the primary ones. Without a distinct "
        "navigation region, visitors (and assistive tech) can't quickly distinguish "
        "\"how do I get around this site\" from links embedded in body content.",
        recommendation="Wrap the primary site navigation in a <nav> element.",
    )]


def _check_primary_link_count(page: ParsedPage, nav_tags) -> List[dict]:
    primary_links = nav_tags[0].find_all("a")
    count = len(primary_links)

    if count == 0:
        return [_finding(
            "warning",
            "Navigation landmark has no links",
            f"{page.url}'s <nav> element contains no links at all — visitors relying on it "
            "to move around the site have nothing to click.",
            recommendation="Add the site's primary section links inside the <nav> element.",
        )]

    if count > MAX_PRIMARY_LINKS:
        return [_finding(
            "info",
            "Primary navigation has a large number of links",
            f"{page.url}'s main navigation contains {count} links (more than "
            f"{MAX_PRIMARY_LINKS}). A long flat list of top-level choices makes it harder "
            "for visitors to scan and pick the right one, and is a common sign navigation "
            "would benefit from grouping into a dropdown/mega-menu structure.",
            recommendation="Group related links under a smaller number of top-level "
                            "categories, using dropdowns/submenus for the rest.",
        )]

    return []


def _check_home_link(page: ParsedPage) -> List[dict]:
    """Looks for a link back to `/` — usually the logo, but any anchor to the root counts."""
    parsed = urlparse(page.url)
    root = f"{parsed.scheme}://{parsed.netloc}/"

    for tag in page.anchor_tags:
        href = (tag.get("href") or "").strip()
        if href in ("/", "", root, root.rstrip("/")):
            return []
        if href == parsed.scheme + "://" + parsed.netloc:
            return []

    # Only worth flagging once there's enough navigation structure that a "way home" is expected.
    if len(page.anchor_tags) < 5:
        return []

    return [_finding(
        "info",
        "No obvious link back to the homepage",
        f"{page.url} has {len(page.anchor_tags)} links, but none point back to the site "
        "root. Visitors who navigate deep into a site commonly expect the logo (or another "
        "obvious link) to take them home.",
        recommendation="Link the site logo (or a persistent nav item) to the homepage root "
                        "URL.",
    )]


def _check_breadcrumbs(page: ParsedPage) -> List[dict]:
    """Only meaningful on pages that are themselves nested (path depth > 1)."""
    parsed = urlparse(page.url)
    depth = len([seg for seg in parsed.path.split("/") if seg])
    if depth < 2:
        return []

    has_breadcrumb_nav = page.soup.find(attrs={"aria-label": lambda v: v and "breadcrumb" in v.lower()})
    has_breadcrumb_class = page.soup.find(
        class_=lambda v: v and any("breadcrumb" in c.lower() for c in (v if isinstance(v, list) else [v]))
    )
    has_breadcrumb_schema = any(
        _is_breadcrumb_list(block) for block in page.json_ld
    )

    if has_breadcrumb_nav or has_breadcrumb_class or has_breadcrumb_schema:
        return []

    return [_finding(
        "info",
        "No breadcrumb trail on a nested page",
        f"{page.url} is {depth} levels deep in the site's URL structure but shows no "
        "breadcrumb trail. Breadcrumbs help visitors understand where a page sits in the "
        "site hierarchy and give them a quick way up to a parent section.",
        recommendation="Add a breadcrumb trail (with BreadcrumbList structured data so "
                        "search engines can show it too) on pages nested more than one "
                        "level deep.",
    )]


def _is_breadcrumb_list(block) -> bool:
    if isinstance(block, dict):
        return block.get("@type") == "BreadcrumbList"
    if isinstance(block, list):
        return any(_is_breadcrumb_list(item) for item in block)
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
