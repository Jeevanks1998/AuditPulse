"""
seo/broken_links.py

Site-level check that actually requests a sample of a page's links and
reports which ones are broken (4xx/5xx), erroring (timeout, DNS,
connection refused), or redirecting. This is the one seo/ module that
makes a request per link rather than reading data already on a
ParsedPage — capped and concurrency-limited so a page with hundreds of
links doesn't turn one audit into hundreds of outbound requests.

Takes crawler.links.Link objects (as extracted by crawler.links.
extract_links), not bare URLs, so callers already holding the per-page
link list from the crawl don't need to re-resolve anything.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional

import httpx

from config.logging import logger
from crawler.links import Link

MODULE = "seo"
CATEGORY = "links"

DEFAULT_MAX_LINKS_CHECKED = 40
DEFAULT_CONCURRENCY = 8
REQUEST_TIMEOUT_SECONDS = 8.0


@dataclass
class LinkCheckResult:
    url: str
    status_code: Optional[int]
    ok: bool
    error: Optional[str] = None
    redirected_to: Optional[str] = None


async def check_broken_links(
    client: httpx.AsyncClient,
    links: List[Link],
    max_links: int = DEFAULT_MAX_LINKS_CHECKED,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> List[dict]:
    """
    Live-checks a deduped sample of `links` (internal and external,
    excluding non-http(s) schemes like mailto:) and returns findings for
    anything broken or erroring. Results are per-URL, not per-occurrence
    — a link repeated on the page is only checked once.
    """
    candidates = _dedupe_checkable(links)[:max_links]
    if not candidates:
        return []

    semaphore = asyncio.Semaphore(max(1, concurrency))
    results = await asyncio.gather(
        *(_check_one(client, semaphore, link, timeout) for link in candidates)
    )

    return _to_findings(results, truncated=len(_dedupe_checkable(links)) > max_links)


def _dedupe_checkable(links: List[Link]) -> List[Link]:
    seen: set = set()
    out: List[Link] = []
    for link in links:
        scheme = link.url.split(":", 1)[0].lower()
        if scheme not in ("http", "https"):
            continue
        if link.url in seen:
            continue
        seen.add(link.url)
        out.append(link)
    return out


async def _check_one(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, link: Link, timeout: float
) -> LinkCheckResult:
    async with semaphore:
        try:
            response = await client.head(link.url, timeout=timeout, follow_redirects=True)
            # Some servers don't implement HEAD correctly (405/501); fall back to GET.
            if response.status_code in (405, 501):
                response = await client.get(link.url, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as exc:
            return LinkCheckResult(url=link.url, status_code=None, ok=False, error=str(exc))

        redirected_to = str(response.url) if str(response.url) != link.url else None
        ok = response.status_code < 400
        return LinkCheckResult(
            url=link.url, status_code=response.status_code, ok=ok, redirected_to=redirected_to,
        )


def _to_findings(results: List[LinkCheckResult], truncated: bool) -> List[dict]:
    findings: List[dict] = []

    broken = [r for r in results if not r.ok and r.status_code is not None]
    errored = [r for r in results if r.error is not None]
    redirected = [r for r in results if r.ok and r.redirected_to]

    if broken:
        sample = ", ".join(f"{r.url} ({r.status_code})" for r in broken[:5])
        extra = f" and {len(broken) - 5} more" if len(broken) > 5 else ""
        severity = "critical" if any((r.status_code or 0) >= 500 for r in broken) else "warning"
        findings.append(_finding(
            severity,
            "Broken links found",
            f"{len(broken)} link(s) returned an error status: {sample}{extra}.",
            recommendation="Fix or remove links pointing at pages that no longer exist or "
                            "error, and set up a redirect for moved content.",
        ))

    if errored:
        sample = ", ".join(r.url for r in errored[:5])
        extra = f" and {len(errored) - 5} more" if len(errored) > 5 else ""
        findings.append(_finding(
            "warning",
            "Links failed to connect",
            f"{len(errored)} link(s) could not be reached at all (timeout, DNS failure, or "
            f"connection refused): {sample}{extra}.",
            recommendation="Verify these URLs are correct and the target servers are "
                            "reachable.",
        ))

    if redirected:
        findings.append(_finding(
            "info",
            "Links point through a redirect",
            f"{len(redirected)} link(s) resolve through at least one redirect before "
            "reaching their final destination, adding latency to every click.",
            recommendation="Update links to point directly at their final URL where "
                            "possible.",
        ))

    if truncated:
        logger.debug("seo.broken_links: link sample truncated by max_links cap")

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
