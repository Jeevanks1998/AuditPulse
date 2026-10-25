"""
Fetches and caches robots.txt per host. Missing or broken robots.txt means
"allow everything", as real crawlers do.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from config.logging import logger

DEFAULT_USER_AGENT = "AuditPulseBot/1.0 (+https://auditpulse.example.com/bot)"
ROBOTS_CACHE_TTL_SECONDS = 3600
ROBOTS_FETCH_TIMEOUT_SECONDS = 10.0


@dataclass
class _RobotsInfo:
    parser: RobotFileParser
    fetched_at: float
    sitemap_urls: List[str] = field(default_factory=list)
    crawl_delay: Optional[float] = None


class RobotsChecker:
    """One per crawl; caches robots.txt per host."""

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout: float = ROBOTS_FETCH_TIMEOUT_SECONDS):
        self.user_agent = user_agent
        self.timeout = timeout
        self._cache: Dict[str, _RobotsInfo] = {}

    async def can_fetch(self, client: httpx.AsyncClient, url: str) -> bool:
        info = await self._get_info(client, url)
        return info.parser.can_fetch(self.user_agent, url)

    async def crawl_delay(self, client: httpx.AsyncClient, url: str) -> Optional[float]:
        info = await self._get_info(client, url)
        return info.crawl_delay

    async def sitemaps(self, client: httpx.AsyncClient, url: str) -> List[str]:
        """Sitemap: lines from robots.txt."""
        info = await self._get_info(client, url)
        return info.sitemap_urls

    async def _get_info(self, client: httpx.AsyncClient, url: str) -> _RobotsInfo:
        parsed = urlparse(url)
        host_key = f"{parsed.scheme}://{parsed.netloc}"

        cached = self._cache.get(host_key)
        if cached and (time.time() - cached.fetched_at) < ROBOTS_CACHE_TTL_SECONDS:
            return cached

        info = await self._fetch(client, host_key)
        self._cache[host_key] = info
        return info

    async def _fetch(self, client: httpx.AsyncClient, host_key: str) -> _RobotsInfo:
        robots_url = f"{host_key}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        sitemap_urls: List[str] = []

        try:
            response = await client.get(
                robots_url, timeout=self.timeout, headers={"User-Agent": self.user_agent}
            )
            if response.status_code == 200:
                lines = response.text.splitlines()
                parser.parse(lines)
                # Sitemap URLs contain colons, so only strip the "sitemap:" prefix.
                sitemap_urls = [
                    line[len("sitemap:"):].strip()
                    for line in lines
                    if line.lower().startswith("sitemap:")
                ]
            else:
                # No robots.txt: allow everything.
                parser.parse([])
        except httpx.HTTPError as exc:
            logger.warning(f"robots.py: failed to fetch {robots_url}, allowing all: {exc}")
            parser.parse([])

        return _RobotsInfo(
            parser=parser,
            fetched_at=time.time(),
            sitemap_urls=sitemap_urls,
            crawl_delay=parser.crawl_delay(self.user_agent),
        )
