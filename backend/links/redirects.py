"""
links/redirects.py

Site-level check that live-requests a sample of a page's links and
inspects the *redirect chain* each one takes before landing on a final
URL — distinct from seo/broken_links.py, which only reports the small
"redirected" bucket as one info-level finding without looking at chain
length or status codes along the way. Here, a chain of more than one
hop, a chain using a temporary (302/307) status where the destination
looks permanent, and a plain-http URL that never actually reaches
https all get their own finding, since each has a different fix.

Makes its own requests the same way seo/broken_links.py does, capped
and concurrency-limited so a page with many links doesn't turn one
audit into dozens of extra requests. See links/loops.py for the
separate, cheaper check that manually walks hops looking for a true
redirect cycle rather than characterizing a normal (non-looping)
chain.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse

import httpx

from config.logging import logger
from crawler.links import Link

MODULE = "links"
CATEGORY = "redirects"

DEFAULT_MAX_LINKS_CHECKED = 40
DEFAULT_CONCURRENCY = 8
REQUEST_TIMEOUT_SECONDS = 8.0
LONG_CHAIN_HOP_THRESHOLD = 2  # more than 1 intermediate hop before the final URL
MAX_EXAMPLES = 5

TEMPORARY_REDIRECT_CODES = {302, 303, 307}


@dataclass
class RedirectCheckResult:
    original_url: str
    final_url: str
    hop_count: int
    hop_status_codes: List[int] = field(default_factory=list)
    error: Optional[str] = None


async def check_redirects(
    client: httpx.AsyncClient,
    links: List[Link],
    max_links: int = DEFAULT_MAX_LINKS_CHECKED,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> List[dict]:
    """
    Live-checks a deduped sample of `links` and returns findings about
    the redirect chain each one takes, if any. Results are per-URL —
    a link repeated on the page is only checked once.
    """
    candidates = _dedupe_checkable(links)
    sample = candidates[:max_links]
    if not sample:
        return []

    semaphore = asyncio.Semaphore(max(1, concurrency))
    results = await asyncio.gather(
        *(_check_one(client, semaphore, link.url, timeout) for link in sample)
    )

    findings: List[dict] = []
    findings += _check_long_chains(results)
    findings += _check_temporary_redirect_to_stable_target(results)
    findings += _check_http_not_upgraded(results)

    if len(candidates) > max_links:
        logger.debug("links.redirects: link sample truncated by max_links cap")

    return findings


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


async def _check_one(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, url: str, timeout: float) -> RedirectCheckResult:
    async with semaphore:
        try:
            response = await client.get(url, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as exc:
            return RedirectCheckResult(original_url=url, final_url=url, hop_count=0, error=str(exc))

        hop_codes = [r.status_code for r in response.history]
        return RedirectCheckResult(
            original_url=url,
            final_url=str(response.url),
            hop_count=len(response.history),
            hop_status_codes=hop_codes,
        )


def _check_long_chains(results: List[RedirectCheckResult]) -> List[dict]:
    long_chains = [r for r in results if r.hop_count > LONG_CHAIN_HOP_THRESHOLD]
    if not long_chains:
        return []

    examples = ", ".join(
        f"{r.original_url} ({r.hop_count} hops → {r.final_url})" for r in long_chains[:MAX_EXAMPLES]
    )
    return [_finding(
        "warning",
        "Long redirect chain before reaching final URL",
        f"{len(long_chains)} link(s) pass through more than {LONG_CHAIN_HOP_THRESHOLD} "
        f"redirect hops before landing on their final URL: {examples}. Each hop adds a full "
        "network round-trip before the destination starts loading.",
        recommendation="Point the link directly at the final destination URL instead of "
                        "relying on a chain of redirects to get there.",
    )]


def _check_temporary_redirect_to_stable_target(results: List[RedirectCheckResult]) -> List[dict]:
    offenders = [
        r for r in results
        if r.hop_status_codes and all(code in TEMPORARY_REDIRECT_CODES for code in r.hop_status_codes)
        and r.original_url != r.final_url
    ]
    if not offenders:
        return []

    examples = ", ".join(f"{r.original_url} → {r.final_url}" for r in offenders[:MAX_EXAMPLES])
    return [_finding(
        "info",
        "Redirect uses a temporary status code",
        f"{len(offenders)} link(s) redirect using only temporary status codes (302/303/307): "
        f"{examples}. If the move is permanent, a temporary code tells search engines to "
        "keep indexing the old URL and not transfer its ranking signals to the new one.",
        recommendation="If the destination has permanently moved, switch the redirect to "
                        "301 (or 308 if the request method must be preserved).",
    )]


def _check_http_not_upgraded(results: List[RedirectCheckResult]) -> List[dict]:
    offenders = [
        r for r in results
        if urlparse(r.original_url).scheme == "http" and urlparse(r.final_url).scheme != "https"
        and r.error is None
    ]
    if not offenders:
        return []

    examples = ", ".join(r.original_url for r in offenders[:MAX_EXAMPLES])
    return [_finding(
        "warning",
        "HTTP link never upgrades to HTTPS",
        f"{len(offenders)} link(s) starting with http:// resolve without ever redirecting "
        f"to https://: {examples}. Traffic through this link travels unencrypted for at "
        "least its first hop.",
        recommendation="Update the link to https:// directly, or configure the target "
                        "server to redirect http requests to https.",
    )]


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
