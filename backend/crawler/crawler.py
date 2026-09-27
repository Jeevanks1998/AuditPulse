"""
crawler/crawler.py

The crawl orchestrator: given a seed URL, fetches pages breadth-first
(concurrency-limited, robots.txt-respecting), seeds the frontier from
the sitemap when doing a full-site run, and hands each fetched page to
parser/links/extractor so the caller gets back a flat CrawlResult with
per-page signals and findings ready for scoring.

This is what `services.audit_service.run_audit_pipeline` swaps in for
its placeholder scoring block — `crawl_site(...)` returns real
per-module findings via `PageResult.signals.findings`, in the same
{module, severity, title, description} shape the placeholder pipeline
already writes to Audit.findings, so the rest of that pipeline (Issue
sync, Consent/Analytics writers, Website rollups) needs no changes.

Usage:
    from crawler import crawl_site

    result = await crawl_site(audit.url, max_pages=audit.max_pages, depth=audit.depth)
    all_findings = [f for page in result.ok_pages for f in page.signals.findings]
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set
from urllib.parse import urlparse

import httpx

from config.constants import DEFAULT_MAX_PAGES
from config.logging import logger
from crawler.extractor import PageSignals, extract_signals
from crawler.links import Link, extract_links, same_site_targets
from crawler.parser import parse_html
from crawler.robots import DEFAULT_USER_AGENT, RobotsChecker
from crawler.sitemap import discover_sitemap_urls

DEFAULT_CONCURRENCY = 5
REQUEST_TIMEOUT_SECONDS = 15.0


@dataclass
class PageResult:
    """Outcome of fetching one URL. `signals`/`links` are only populated when `ok` is True."""

    url: str
    status_code: Optional[int]
    ok: bool
    fetch_ms: int
    signals: Optional[PageSignals] = None
    links: List[Link] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class CrawlResult:
    start_url: str
    pages: List[PageResult] = field(default_factory=list)
    pages_crawled: int = 0
    pages_skipped_robots: int = 0
    duration_ms: int = 0

    @property
    def ok_pages(self) -> List[PageResult]:
        return [p for p in self.pages if p.ok and p.signals is not None]

    @property
    def all_findings(self) -> List[dict]:
        return [finding for page in self.ok_pages for finding in page.signals.findings]


class Crawler:
    """
    One instance per audit run. Not safe to reuse across concurrent
    calls to `run()` — construct a fresh Crawler per crawl.
    """

    def __init__(
        self,
        start_url: str,
        max_pages: int = DEFAULT_MAX_PAGES,
        depth: str = "full",
        user_agent: str = DEFAULT_USER_AGENT,
        concurrency: int = DEFAULT_CONCURRENCY,
    ):
        self.start_url = start_url
        self.max_pages = max(1, max_pages)
        self.depth = depth  # "homepage" | "full"
        self.user_agent = user_agent
        self.hostname = urlparse(start_url).hostname or ""
        self.robots = RobotsChecker(user_agent=user_agent)
        self._concurrency = max(1, concurrency)
        self._semaphore = asyncio.Semaphore(self._concurrency)

    async def run(self) -> CrawlResult:
        started = time.monotonic()
        result = CrawlResult(start_url=self.start_url)
        visited: Set[str] = {self.start_url}
        queue: asyncio.Queue = asyncio.Queue()
        await queue.put(self.start_url)

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": self.user_agent},
        ) as client:
            if self.depth == "full":
                for seeded_url in await self._seed_from_sitemap(client):
                    if seeded_url not in visited and len(visited) < self.max_pages:
                        visited.add(seeded_url)
                        await queue.put(seeded_url)

            while not queue.empty() and result.pages_crawled < self.max_pages:
                batch = await self._drain_batch(queue, result.pages_crawled)
                fetched = await asyncio.gather(*(self._fetch_one(client, url) for url in batch))

                for page_result in fetched:
                    result.pages.append(page_result)
                    result.pages_crawled += 1
                    if page_result.error == "disallowed by robots.txt":
                        result.pages_skipped_robots += 1

                    if page_result.ok and self.depth == "full":
                        for link_url in same_site_targets(page_result.links):
                            if link_url not in visited and len(visited) < self.max_pages:
                                visited.add(link_url)
                                await queue.put(link_url)

                if self.depth == "homepage":
                    break

        result.duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            f"Crawler: {result.pages_crawled} page(s) fetched for {self.start_url} "
            f"in {result.duration_ms}ms ({result.pages_skipped_robots} skipped by robots.txt)"
        )
        return result

    async def _drain_batch(self, queue: asyncio.Queue, already_crawled: int) -> List[str]:
        """Pulls up to `concurrency` URLs off the queue, capped by remaining page budget."""
        batch: List[str] = []
        remaining = self.max_pages - already_crawled
        while not queue.empty() and len(batch) < self._concurrency and len(batch) < remaining:
            batch.append(await queue.get())
        return batch

    async def _seed_from_sitemap(self, client: httpx.AsyncClient) -> List[str]:
        try:
            declared = await self.robots.sitemaps(client, self.start_url)
            return await discover_sitemap_urls(client, self.start_url, known_sitemaps=declared)
        except Exception as exc:  # noqa: BLE001 — sitemap seeding is best-effort
            logger.warning(f"Crawler: sitemap discovery failed for {self.start_url}: {exc}")
            return []

    async def _fetch_one(self, client: httpx.AsyncClient, url: str) -> PageResult:
        async with self._semaphore:
            try:
                if not await self.robots.can_fetch(client, url):
                    return PageResult(url=url, status_code=None, ok=False, fetch_ms=0, error="disallowed by robots.txt")
            except Exception as exc:  # noqa: BLE001 — robots lookup failure shouldn't block the fetch
                logger.debug(f"Crawler: robots.txt check failed for {url}, allowing: {exc}")

            start = time.monotonic()
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                return PageResult(url=url, status_code=None, ok=False, fetch_ms=elapsed_ms, error=str(exc))

            elapsed_ms = int((time.monotonic() - start) * 1000)
            content_type = response.headers.get("content-type", "")

            if response.status_code >= 400:
                return PageResult(
                    url=url, status_code=response.status_code, ok=False,
                    fetch_ms=elapsed_ms, error=f"HTTP {response.status_code}",
                )
            if "text/html" not in content_type:
                return PageResult(
                    url=url, status_code=response.status_code, ok=True, fetch_ms=elapsed_ms,
                    error=None,  # fetched fine, just nothing to parse (e.g. a PDF the sitemap listed)
                )

            page = parse_html(url, response.text)
            links = extract_links(page, self.hostname)
            signals = extract_signals(page, links)
            return PageResult(
                url=url, status_code=response.status_code, ok=True,
                fetch_ms=elapsed_ms, signals=signals, links=links,
            )


async def crawl_site(start_url: str, max_pages: int = DEFAULT_MAX_PAGES, depth: str = "full") -> CrawlResult:
    """Module-level convenience wrapper — the function services.audit_service imports."""
    crawler = Crawler(start_url=start_url, max_pages=max_pages, depth=depth)
    return await crawler.run()
