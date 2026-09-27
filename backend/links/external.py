"""
links/external.py

Page-level checks on a page's links to other domains: target="_blank"
links missing rel="noopener" (the classic reverse-tabnabbing gap — the
opened page can reach back into window.opener and redirect the
original tab), plain-http links out from an otherwise-https page, and
a page so dominated by outbound links that it reads more like a link
farm than content. Distinct from security/mixed_content.py, which
looks at a page's own *loaded resources* (scripts, images, styles)
over http — this looks at *outbound navigation* links, a different
attack surface and a different fix.

Takes the crawler.links.Link list a caller already resolved for the
page, same as links/internal.py.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlparse

from crawler.links import Link
from crawler.parser import ParsedPage

MODULE = "links"
CATEGORY = "external"

HIGH_EXTERNAL_LINK_COUNT = 100
MAX_EXAMPLES = 5


def check_external_links(page: ParsedPage, links: List[Link]) -> List[dict]:
    """Findings for a page's external links: tabnabbing risk, insecure targets, and link-farm volume."""
    external = [link for link in links if not link.is_internal and not link.is_asset]

    findings: List[dict] = []
    findings += _check_target_blank_without_noopener(page, external)
    findings += _check_insecure_external_links(page, external)
    findings += _check_excessive_external_links(page, external)
    return findings


def _check_target_blank_without_noopener(page: ParsedPage, external: List[Link]) -> List[dict]:
    external_urls = {link.url for link in external}
    offenders = []

    for tag in page.soup.find_all("a", href=True):
        if (tag.get("target") or "").lower() != "_blank":
            continue
        href = tag.get("href", "").strip()
        rel_values = tag.get("rel") or []
        rel_values = [rel_values] if isinstance(rel_values, str) else rel_values
        rel_lower = {r.lower() for r in rel_values}
        if "noopener" in rel_lower or "noreferrer" in rel_lower:
            continue
        offenders.append(href)

    if not offenders:
        return []

    examples = ", ".join(offenders[:MAX_EXAMPLES])
    return [_finding(
        "warning",
        "target=\"_blank\" link missing rel=\"noopener\"",
        f"{page.url} has {len(offenders)} link(s) opening in a new tab without "
        f"rel=\"noopener\" (or \"noreferrer\"): {examples}. The opened page gets a live "
        "window.opener reference back to this tab and can navigate it to a different URL — "
        "a phishing technique known as reverse tabnabbing — and it also gets a full "
        "Referer header revealing where the click came from.",
        recommendation="Add rel=\"noopener\" (or \"noopener noreferrer\" to also suppress "
                        "the referrer) to every target=\"_blank\" link.",
    )]


def _check_insecure_external_links(page: ParsedPage, external: List[Link]) -> List[dict]:
    if urlparse(page.url).scheme != "https":
        return []  # the page itself isn't https; not this check's concern

    insecure = [link for link in external if urlparse(link.url).scheme == "http"]
    if not insecure:
        return []

    examples = ", ".join(link.url for link in insecure[:MAX_EXAMPLES])
    return [_finding(
        "info",
        "External links point to plain HTTP",
        f"{page.url} (served over https) links out to {len(insecure)} external URL(s) still "
        f"on plain http: {examples}. Clicking through sends the referring URL and any "
        "session/query data in the request unencrypted, and the destination itself may not "
        "support https at all.",
        recommendation="Where the destination supports it, link to the https version "
                        "instead of http.",
    )]


def _check_excessive_external_links(page: ParsedPage, external: List[Link]) -> List[dict]:
    unique_domains = {urlparse(link.url).hostname for link in external if urlparse(link.url).hostname}
    if len(external) < HIGH_EXTERNAL_LINK_COUNT:
        return []

    return [_finding(
        "info",
        "Very high number of external links",
        f"{page.url} has {len(external)} external links across {len(unique_domains)} "
        f"distinct domain(s). Pages this dominated by outbound links (directories, link "
        "pages) are often treated with suspicion by search engines and can dilute whatever "
        "link equity the page has to offer.",
        recommendation="Confirm this volume of outbound linking is intentional; if the page "
                        "is a curated directory that's usually fine, but unintentional link "
                        "sprawl (e.g. from unmoderated user content) is worth cleaning up.",
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
