"""
seo/open_graph.py

Page-level Open Graph (og:*) checks. These tags control how a link
looks when shared on Facebook, LinkedIn, Slack, iMessage, and most other
link-unfurling surfaces — missing or broken values here mean the site's
own content shows up as a bare, unstyled link when someone shares it.

Reads straight from crawler.parser.ParsedPage.meta, which already
lowercases the name/property key, so `og:title` etc. are looked up
directly with no re-parsing.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlparse

from crawler.parser import ParsedPage

MODULE = "seo"
CATEGORY = "open_graph"

REQUIRED_OG_TAGS = ("og:title", "og:description", "og:image", "og:url")


def check_open_graph(page: ParsedPage) -> List[dict]:
    """Findings for one page's Open Graph tags."""
    meta = page.meta or {}
    present = [tag for tag in REQUIRED_OG_TAGS if (meta.get(tag) or "").strip()]

    if not present:
        return [_finding(
            "warning",
            "No Open Graph tags found",
            f"{page.url} has no og:* meta tags. Shared links (Slack, Facebook, LinkedIn, "
            "iMessage, etc.) will fall back to whatever those platforms can scrape from the "
            "page, which is usually a worse preview.",
            recommendation="Add og:title, og:description, og:image, and og:url meta tags.",
        )]

    findings: List[dict] = []
    missing = [tag for tag in REQUIRED_OG_TAGS if tag not in present]
    if missing:
        findings.append(_finding(
            "info",
            "Incomplete Open Graph tags",
            f"{page.url} has some Open Graph tags but is missing: {', '.join(missing)}.",
            recommendation=f"Add the missing tag(s): {', '.join(missing)}.",
        ))

    og_image = (meta.get("og:image") or "").strip()
    if og_image:
        parsed = urlparse(og_image)
        if not parsed.scheme or not parsed.netloc:
            findings.append(_finding(
                "warning",
                "og:image is not an absolute URL",
                f"og:image on {page.url} is \"{og_image}\", a relative path. Most platforms "
                "unfurling the link won't resolve it and will show no image.",
                recommendation="Use a full absolute URL for og:image (https://example.com/"
                                "image.jpg).",
            ))

    og_title = (meta.get("og:title") or "").strip()
    if og_title and len(og_title) > 95:
        findings.append(_finding(
            "info",
            "og:title is long",
            f"og:title on {page.url} is {len(og_title)} characters; most surfaces truncate "
            "well before 95 characters.",
            recommendation="Keep og:title under roughly 60-90 characters.",
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
