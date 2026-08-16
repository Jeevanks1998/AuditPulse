"""
seo/canonical.py

Page-level rel=canonical checks: presence, whether it's a resolvable
absolute URL, whether it points at a different URL than the page it's
on (not necessarily wrong, but worth surfacing), and whether the page
declares more than one canonical tag (invalid — engines will pick one
arbitrarily). crawler.parser.ParsedPage only keeps the *first* canonical
it finds, so the multiple-tag check re-scans page.soup directly.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urldefrag, urlparse

from crawler.parser import ParsedPage

MODULE = "seo"
CATEGORY = "canonical"


def check_canonical(page: ParsedPage) -> List[dict]:
    """Findings for one page's canonical link tag."""
    findings: List[dict] = []

    canonical_tags = _find_canonical_tags(page)
    if len(canonical_tags) > 1:
        findings.append(_finding(
            "warning",
            "Multiple canonical tags",
            f"{page.url} declares {len(canonical_tags)} rel=canonical links. Engines will "
            "pick one and ignore the rest, which may not be the one intended.",
            recommendation="Keep exactly one rel=canonical link tag per page.",
        ))

    canonical = page.canonical
    if not canonical:
        findings.append(_finding(
            "info",
            "Missing canonical link",
            f"{page.url} has no rel=canonical link tag. Without one, engines infer the "
            "canonical version themselves — usually fine for a simple site, but risky if "
            "the same content is reachable through more than one URL (params, trailing "
            "slashes, http/https, www/non-www).",
            recommendation="Add a self-referencing rel=canonical link on every indexable page.",
        ))
        return findings

    parsed = urlparse(canonical)
    if not parsed.scheme or not parsed.netloc:
        findings.append(_finding(
            "warning",
            "Canonical URL is not absolute",
            f"The canonical tag on {page.url} points to \"{canonical}\", a relative URL. "
            "Some crawlers resolve this correctly, but the spec calls for an absolute URL.",
            recommendation="Use a full absolute URL (https://example.com/page) in the "
                            "canonical tag.",
        ))
        return findings

    page_no_frag, _ = urldefrag(page.url)
    canonical_no_frag, _ = urldefrag(canonical)
    if page_no_frag.rstrip("/") != canonical_no_frag.rstrip("/"):
        findings.append(_finding(
            "info",
            "Canonical points to a different URL",
            f"{page.url} declares its canonical as {canonical}. This is normal for "
            "intentional duplicates (e.g. a filtered/paginated view canonicalizing to the "
            "main page) but worth double-checking it isn't accidental.",
            recommendation="Confirm this page is meant to defer to the canonical target "
                            "rather than rank on its own.",
        ))

    return findings


def _find_canonical_tags(page: ParsedPage) -> List[str]:
    hrefs: List[str] = []
    for tag in page.soup.find_all("link"):
        rel = tag.get("rel") or []
        rel = [rel] if isinstance(rel, str) else rel
        if any(r.lower() == "canonical" for r in rel) and tag.get("href"):
            hrefs.append(tag["href"].strip())
    return hrefs


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
