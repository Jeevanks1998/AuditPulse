"""
crawler/sitemap.py

Discovers and flattens a site's sitemap(s) into a plain list of page
URLs. Recurses through <sitemapindex> trees (a sitemap of sitemaps) and
follows whatever `Sitemap:` lines robots.py found in robots.txt, plus a
couple of conventional default paths, so the crawler can seed its
frontier from the site's own published URL list rather than relying
purely on link-following (useful for sites with thin nav or JS-only
menus).

Every fetch/parse failure here is swallowed and logged rather than
raised — a broken or absent sitemap should never stop the crawl, it
just means the frontier starts smaller and grows from link discovery
instead.
"""

from __future__ import annotations

import gzip
from io import BytesIO
from typing import List, Optional, Set
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import httpx

from config.logging import logger

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
DEFAULT_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml")
MAX_URLS = 5000            # hard cap on how many URLs we'll ever return
MAX_NESTED_SITEMAPS = 25   # guards against a pathological/looping sitemap index
FETCH_TIMEOUT_SECONDS = 10.0


async def discover_sitemap_urls(
    client: httpx.AsyncClient,
    base_url: str,
    known_sitemaps: Optional[List[str]] = None,
    timeout: float = FETCH_TIMEOUT_SECONDS,
) -> List[str]:
    """
    Returns a deduped, capped list of page URLs pulled from every
    sitemap this site declares (robots.txt-listed ones first, falling
    back to the conventional /sitemap.xml / /sitemap_index.xml paths).
    """
    candidates = list(known_sitemaps or [])
    for path in DEFAULT_SITEMAP_PATHS:
        candidates.append(urljoin(base_url, path))

    seen_sitemaps: Set[str] = set()
    seen_urls: Set[str] = set()
    urls: List[str] = []

    for sitemap_url in candidates:
        if len(urls) >= MAX_URLS:
            break
        found = await _fetch_and_parse(client, sitemap_url, timeout, seen_sitemaps)
        for url in found:
            if url not in seen_urls:
                seen_urls.add(url)
                urls.append(url)
                if len(urls) >= MAX_URLS:
                    break

    return urls


async def _fetch_and_parse(
    client: httpx.AsyncClient,
    sitemap_url: str,
    timeout: float,
    seen_sitemaps: Set[str],
) -> List[str]:
    if sitemap_url in seen_sitemaps or len(seen_sitemaps) >= MAX_NESTED_SITEMAPS:
        return []
    seen_sitemaps.add(sitemap_url)

    try:
        response = await client.get(sitemap_url, timeout=timeout)
        if response.status_code != 200:
            return []
        raw = response.content
        if sitemap_url.endswith(".gz") or response.headers.get("content-encoding") == "gzip":
            try:
                raw = gzip.GzipFile(fileobj=BytesIO(raw)).read()
            except OSError:
                pass  # not actually gzipped despite the hint; parse as-is
        root = ET.fromstring(raw)
    except (httpx.HTTPError, ET.ParseError) as exc:
        logger.debug(f"sitemap.py: skipping {sitemap_url}: {exc}")
        return []

    tag = root.tag.lower()

    if tag.endswith("sitemapindex"):
        nested_urls = [_loc_text(entry) for entry in root.findall(f"{SITEMAP_NS}sitemap")]
        nested_urls = [u for u in nested_urls if u]
        urls: List[str] = []
        for nested in nested_urls:
            urls.extend(await _fetch_and_parse(client, nested, timeout, seen_sitemaps))
        return urls

    if tag.endswith("urlset"):
        return [u for u in (_loc_text(entry) for entry in root.findall(f"{SITEMAP_NS}url")) if u]

    return []


def _loc_text(entry: ET.Element) -> Optional[str]:
    loc = entry.find(f"{SITEMAP_NS}loc")
    if loc is not None and loc.text:
        return loc.text.strip()
    return None
