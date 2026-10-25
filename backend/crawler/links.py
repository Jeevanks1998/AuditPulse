"""
Turns a page's links into absolute URLs and sorts them: same-site pages to
crawl, external links, or things not to crawl (mailto:, files, ...).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List
from urllib.parse import urldefrag, urljoin, urlparse

from crawler.parser import ParsedPage

NON_CRAWLABLE_SCHEMES = {"mailto", "tel", "sms", "javascript", "data", "ftp"}

ASSET_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".mp3", ".mp4", ".mov", ".avi", ".webm", ".wav",
    ".css", ".js", ".json", ".xml", ".rss",
}


@dataclass
class Link:
    url: str          # absolute, without #fragment
    text: str
    is_internal: bool
    is_asset: bool
    is_crawlable: bool  # same site, not a file, http(s)
    nofollow: bool


def extract_links(page: ParsedPage, base_hostname: str) -> List[Link]:
    """Every <a href> on the page, resolved and de-duplicated."""
    seen: set = set()
    links: List[Link] = []

    for tag in page.anchor_tags:
        href = (tag.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue

        absolute = _resolve(page.url, href)
        if absolute is None:
            continue

        absolute, _ = urldefrag(absolute)
        if absolute in seen:
            continue
        seen.add(absolute)

        parsed = urlparse(absolute)
        scheme_crawlable = parsed.scheme in ("http", "https")
        is_internal = scheme_crawlable and _hostname_matches(parsed.hostname, base_hostname)
        is_asset = _looks_like_asset(parsed.path)
        rel_values = (tag.get("rel") or [])
        rel_values = [rel_values] if isinstance(rel_values, str) else rel_values
        nofollow = any(r.lower() == "nofollow" for r in rel_values)

        links.append(
            Link(
                url=absolute,
                text=tag.get_text(strip=True),
                is_internal=is_internal,
                is_asset=is_asset,
                is_crawlable=scheme_crawlable and is_internal and not is_asset,
                nofollow=nofollow,
            )
        )

    return links


def same_site_targets(links: List[Link]) -> List[str]:
    """URLs worth adding to the crawl queue."""
    seen: set = set()
    targets: List[str] = []
    for link in links:
        if link.is_crawlable and link.url not in seen:
            seen.add(link.url)
            targets.append(link.url)
    return targets


def _resolve(base_url: str, href: str) -> str | None:
    try:
        return urljoin(base_url, href)
    except ValueError:
        return None


def _hostname_matches(candidate: str | None, base_hostname: str) -> bool:
    """www. and the bare domain count as the same site."""
    if not candidate:
        return False
    candidate = candidate.lower().removeprefix("www.")
    base = base_hostname.lower().removeprefix("www.")
    return candidate == base


def _looks_like_asset(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(ext) for ext in ASSET_EXTENSIONS)
