"""
seo/robots.py

Site-level robots.txt checks. Distinct from crawler/robots.py, which
fetches and caches robots.txt purely so the crawler itself can respect
it (`can_fetch`) — this module fetches the same file and turns it into
audit findings: whether it exists, whether it blanket-blocks the whole
site, whether it declares a sitemap, and whether it parses cleanly.

Uses the stdlib's RobotFileParser directly rather than importing
crawler.robots.RobotsChecker, since that class is built around
long-lived per-hostname caching for a multi-page crawl and this is a
single one-off fetch+report.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from config.logging import logger

MODULE = "seo"
CATEGORY = "robots"

DEFAULT_USER_AGENT = "AuditPulseBot/1.0 (+https://auditpulse.example.com/bot)"
FETCH_TIMEOUT_SECONDS = 10.0


async def check_robots(
    client: httpx.AsyncClient,
    base_url: str,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = FETCH_TIMEOUT_SECONDS,
) -> List[dict]:
    """Validates the site's robots.txt and returns findings about it."""
    parsed_base = urlparse(base_url)
    host_root = f"{parsed_base.scheme}://{parsed_base.netloc}"
    robots_url = f"{host_root}/robots.txt"

    try:
        response = await client.get(robots_url, timeout=timeout, headers={"User-Agent": user_agent})
    except httpx.HTTPError as exc:
        logger.debug(f"seo.robots: failed to fetch {robots_url}: {exc}")
        return [_finding(
            "info",
            "robots.txt could not be fetched",
            f"{robots_url} could not be reached ({exc}). Search engines will assume "
            "everything is crawlable, which is usually fine but means there's no explicit "
            "sitemap declaration or crawl guidance either.",
            recommendation="Publish a robots.txt at the site root, even a permissive one.",
        )]

    if response.status_code == 404:
        return [_finding(
            "info",
            "No robots.txt found",
            f"{robots_url} returned 404. Its absence is treated as \"allow everything\" by "
            "every major crawler, so this isn't blocking indexing — but it's also a missed "
            "place to declare a sitemap and set crawl-rate guidance.",
            recommendation="Add a robots.txt at the site root with at least a Sitemap: line.",
        )]

    if response.status_code >= 400:
        return [_finding(
            "warning",
            "robots.txt returned an error",
            f"{robots_url} returned HTTP {response.status_code} instead of 200 or 404, which "
            "some crawlers treat as \"block everything\" out of caution rather than falling "
            "back to allow-all.",
            recommendation="Fix the server error so robots.txt returns 200 (or a clean 404 "
                            "if none is intended).",
        )]

    body = response.text
    findings: List[dict] = []

    parser = RobotFileParser()
    parser.set_url(robots_url)
    lines = body.splitlines()
    parser.parse(lines)

    if not parser.can_fetch(user_agent, host_root + "/"):
        findings.append(_finding(
            "critical",
            "robots.txt blocks the entire site",
            f"{robots_url} disallows crawling of \"/\" for user-agent(s) that match "
            f"\"{user_agent}\" (and likely \"*\"), which tells every well-behaved search "
            "engine not to crawl any page on the site.",
            recommendation="Remove the blanket Disallow: / rule unless the site is meant to "
                            "be completely deindexed.",
        ))

    sitemap_lines = [line for line in lines if line.strip().lower().startswith("sitemap:")]
    if not sitemap_lines:
        findings.append(_finding(
            "info",
            "robots.txt doesn't declare a sitemap",
            f"{robots_url} has no Sitemap: line. This isn't required, but it's the standard "
            "way to point every crawler at the sitemap without relying on them guessing "
            "/sitemap.xml.",
            recommendation="Add a line like \"Sitemap: https://example.com/sitemap.xml\".",
        ))

    if not body.strip():
        findings.append(_finding(
            "info",
            "robots.txt is empty",
            f"{robots_url} returned 200 with an empty body. This is equivalent to allowing "
            "everything, but an empty file is often a sign it wasn't actually configured.",
            recommendation="Either leave robots.txt out entirely (a clean 404) or populate "
                            "it intentionally.",
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
