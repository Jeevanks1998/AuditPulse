"""
seo/meta.py

Page-level <meta> checks: the description tag search engines most often
show as a snippet, the robots meta directive that can silently keep a
page out of the index entirely, and a charset sanity check. Reads
straight from crawler.parser.ParsedPage.meta, which is already a
lowercased name/property -> content dict, so no re-parsing happens here.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from crawler.parser import ParsedPage

MODULE = "seo"
CATEGORY = "meta"

META_DESC_MIN_LEN = 70
META_DESC_MAX_LEN = 160
NOINDEX_TOKENS = {"noindex"}
NOFOLLOW_TOKENS = {"nofollow"}


def check_meta(page: ParsedPage) -> List[dict]:
    """Findings for one page's meta description, robots directive, and charset."""
    findings: List[dict] = []
    findings += _check_description(page)
    findings += _check_robots_meta(page)
    findings += _check_charset(page)
    return findings


def _check_description(page: ParsedPage) -> List[dict]:
    description = (page.meta.get("description") or "").strip()
    findings: List[dict] = []

    if not description:
        findings.append(_finding(
            "warning",
            "Missing meta description",
            f"{page.url} has no meta description tag. Search engines will generate a "
            "snippet from page content instead, which you don't control.",
            recommendation=f"Add a meta description between {META_DESC_MIN_LEN} and "
                            f"{META_DESC_MAX_LEN} characters that summarizes the page and "
                            "invites a click.",
        ))
        return findings

    length = len(description)
    if length < META_DESC_MIN_LEN:
        findings.append(_finding(
            "info",
            "Meta description is short",
            f"Meta description on {page.url} is {length} characters; there's room to say "
            f"more before hitting the ~{META_DESC_MAX_LEN}-character truncation point.",
            recommendation=f"Expand toward {META_DESC_MIN_LEN}-{META_DESC_MAX_LEN} characters.",
        ))
    elif length > META_DESC_MAX_LEN:
        findings.append(_finding(
            "info",
            "Meta description is too long",
            f"Meta description on {page.url} is {length} characters and will likely be "
            f"truncated in search results past ~{META_DESC_MAX_LEN} characters.",
            recommendation=f"Trim to {META_DESC_MIN_LEN}-{META_DESC_MAX_LEN} characters.",
        ))

    return findings


def _check_robots_meta(page: ParsedPage) -> List[dict]:
    raw = (page.meta.get("robots") or "").strip().lower()
    if not raw:
        return []

    directives = {token.strip() for token in raw.split(",") if token.strip()}
    findings: List[dict] = []

    if directives & NOINDEX_TOKENS:
        findings.append(_finding(
            "critical",
            "Page is set to noindex",
            f"{page.url} has <meta name=\"robots\" content=\"{raw}\">, which tells search "
            "engines not to index it. If this page is meant to rank, the tag is likely "
            "left over from staging or a template default.",
            recommendation="Remove the noindex directive if this page should appear in "
                            "search results, or confirm it's intentional if not.",
        ))

    if directives & NOFOLLOW_TOKENS:
        findings.append(_finding(
            "info",
            "Page-level nofollow is set",
            f"{page.url} has a page-wide nofollow directive, so search engines won't pass "
            "authority through any links on this page.",
            recommendation="Confirm this is intentional — page-wide nofollow is unusual "
                            "outside of user-generated or untrusted content pages.",
        ))

    return findings


def _check_charset(page: ParsedPage) -> List[dict]:
    # crawler.parser only captures name/property meta tags (charset uses a
    # bare `charset` attribute instead), so this can't see a real
    # <meta charset="utf-8">; it only catches the http-equiv content-type
    # variant, which does land in page.meta. Best-effort, not exhaustive.
    has_charset = "content-type" in page.meta
    if has_charset:
        return []
    return [_finding(
        "info",
        "No character encoding declared",
        f"{page.url} doesn't declare a charset (e.g. <meta charset=\"utf-8\">). Browsers "
        "will guess, which can misrender non-ASCII text.",
        recommendation="Add <meta charset=\"utf-8\"> as the first tag inside <head>.",
    )]


def check_duplicate_meta_descriptions(page_descriptions: Dict[str, Optional[str]]) -> List[dict]:
    """
    Site-level check across a crawl. `page_descriptions` maps
    url -> meta description text. Flags descriptions reused across more
    than one URL, same rationale as seo.title.check_duplicate_titles.
    """
    by_description: Dict[str, List[str]] = defaultdict(list)
    for url, description in page_descriptions.items():
        normalized = (description or "").strip().lower()
        if normalized:
            by_description[normalized].append(url)

    findings: List[dict] = []
    for normalized, urls in by_description.items():
        if len(urls) > 1:
            shown = ", ".join(urls[:5])
            extra = f" and {len(urls) - 5} more" if len(urls) > 5 else ""
            findings.append(_finding(
                "info",
                "Duplicate meta description across pages",
                f"{len(urls)} pages share the same meta description: {shown}{extra}.",
                recommendation="Write a unique meta description for each page.",
            ))
    return findings


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
