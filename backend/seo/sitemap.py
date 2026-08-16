"""
seo/sitemap.py

Site-level sitemap checks. Distinct from crawler/sitemap.py, which only
*discovers and flattens* sitemap URLs to seed the crawl frontier — this
module fetches the same files but *validates* them and returns findings
(missing, invalid XML, over the protocol's size limits, no lastmod
dates) rather than a bare URL list. The two don't share request/parse
code because their failure handling is opposite: discovery treats any
problem as "return fewer URLs and move on", validation treats the same
problem as "that's the finding".

Every fetch/parse failure here still degrades gracefully to a finding
rather than an exception — a broken sitemap should show up as an audit
result, not crash the pipeline.
"""

from __future__ import annotations

import gzip
from io import BytesIO
from typing import List, Optional
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import httpx

from config.logging import logger

MODULE = "seo"
CATEGORY = "sitemap"

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
DEFAULT_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml")
FETCH_TIMEOUT_SECONDS = 10.0

# Protocol limits from sitemaps.org — exceeding either means the file
# itself is invalid for at least some consumers.
MAX_URLS_PER_SITEMAP = 50_000
MAX_SITEMAP_BYTES = 50 * 1024 * 1024


async def check_sitemap(
    client: httpx.AsyncClient,
    base_url: str,
    known_sitemaps: Optional[List[str]] = None,
    timeout: float = FETCH_TIMEOUT_SECONDS,
) -> List[dict]:
    """
    Validates the site's sitemap(s): declared in robots.txt via
    `known_sitemaps` if seo.robots already found any, falling back to
    the conventional /sitemap.xml / /sitemap_index.xml paths.
    """
    candidates = list(known_sitemaps or [])
    for path in DEFAULT_SITEMAP_PATHS:
        candidates.append(urljoin(base_url, path))

    for sitemap_url in candidates:
        result = await _fetch(client, sitemap_url, timeout)
        if result is not None:
            return await _validate(client, sitemap_url, result, timeout)

    return [_finding(
        "warning",
        "No sitemap found",
        f"No sitemap was found at any of: {', '.join(candidates)}. Sitemaps aren't required, "
        "but they help search engines discover pages faster, especially on large or "
        "poorly-interlinked sites.",
        recommendation="Publish a sitemap.xml and reference it with a Sitemap: line in "
                        "robots.txt.",
    )]


async def _fetch(client: httpx.AsyncClient, url: str, timeout: float) -> Optional[bytes]:
    try:
        response = await client.get(url, timeout=timeout)
    except httpx.HTTPError as exc:
        logger.debug(f"seo.sitemap: failed to fetch {url}: {exc}")
        return None
    if response.status_code != 200:
        return None

    raw = response.content
    if url.endswith(".gz") or response.headers.get("content-encoding") == "gzip":
        try:
            raw = gzip.GzipFile(fileobj=BytesIO(raw)).read()
        except OSError:
            pass  # hint said gzip but body wasn't; fall through and let XML parsing fail
    return raw


async def _validate(
    client: httpx.AsyncClient, url: str, raw: bytes, timeout: float
) -> List[dict]:
    findings: List[dict] = []

    if len(raw) > MAX_SITEMAP_BYTES:
        findings.append(_finding(
            "warning",
            "Sitemap exceeds the 50MB size limit",
            f"{url} is {len(raw) / (1024 * 1024):.1f}MB uncompressed, over the sitemaps.org "
            "50MB limit; some consumers may refuse to process it.",
            recommendation="Split the sitemap into multiple files under a sitemap index.",
        ))

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        findings.append(_finding(
            "critical",
            "Sitemap is not valid XML",
            f"{url} could not be parsed as XML ({exc}). Search engines will ignore it "
            "entirely until it's fixed.",
            recommendation="Validate the sitemap's XML (e.g. with an XML linter) and fix "
                            "the malformed markup.",
        ))
        return findings

    tag = root.tag.lower()

    if tag.endswith("sitemapindex"):
        entries = root.findall(f"{SITEMAP_NS}sitemap")
        if not entries:
            findings.append(_finding(
                "warning",
                "Sitemap index has no entries",
                f"{url} is a <sitemapindex> but lists no child sitemaps.",
                recommendation="Add <sitemap> entries pointing at the site's actual sitemap "
                                "files, or replace this with a single <urlset> sitemap.",
            ))
        return findings

    if tag.endswith("urlset"):
        entries = root.findall(f"{SITEMAP_NS}url")
        if not entries:
            findings.append(_finding(
                "warning",
                "Sitemap has no URLs",
                f"{url} is a <urlset> but lists no <url> entries.",
                recommendation="Add <url> entries for the pages you want indexed, or remove "
                                "the sitemap if the site is genuinely empty.",
            ))
            return findings

        if len(entries) > MAX_URLS_PER_SITEMAP:
            findings.append(_finding(
                "warning",
                "Sitemap exceeds 50,000 URLs",
                f"{url} lists {len(entries)} URLs, over the sitemaps.org limit of "
                f"{MAX_URLS_PER_SITEMAP:,} per file.",
                recommendation="Split into multiple sitemap files referenced from a "
                                "sitemap index.",
            ))

        missing_lastmod = sum(1 for e in entries if e.find(f"{SITEMAP_NS}lastmod") is None)
        if missing_lastmod:
            findings.append(_finding(
                "info",
                "Sitemap entries missing lastmod",
                f"{missing_lastmod} of {len(entries)} URL entries in {url} have no <lastmod> "
                "date, which search engines use to prioritize re-crawling changed pages.",
                recommendation="Add a <lastmod> date (ISO 8601) to each <url> entry, kept "
                                "accurate when the page actually changes.",
            ))
        return findings

    findings.append(_finding(
        "warning",
        "Unrecognized sitemap format",
        f"{url} is valid XML but its root element (<{root.tag}>) is neither <urlset> nor "
        "<sitemapindex>.",
        recommendation="Use the standard sitemap protocol format (urlset or sitemapindex).",
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
