"""
links/loops.py

Detects true redirect cycles (A -> B -> A) and runaway chains that
never terminate, as opposed to links/redirects.py's job of
characterizing a normal, terminating chain (length, status codes).
httpx's own follow_redirects=True raises TooManyRedirects past its
internal cap without saying whether it was a genuine cycle or just a
long chain, so this walks hops manually — one un-followed request at a
time, tracking every URL visited — to tell the two apart and name the
exact URL where the cycle closes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

from config.logging import logger
from crawler.links import Link

MODULE = "links"
CATEGORY = "loops"

DEFAULT_MAX_LINKS_CHECKED = 40
DEFAULT_CONCURRENCY = 8
REQUEST_TIMEOUT_SECONDS = 8.0
MAX_HOPS = 15  # generous ceiling; a real chain rarely needs more than a handful
MAX_EXAMPLES = 5

REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


@dataclass
class LoopCheckResult:
    original_url: str
    is_loop: bool = False
    loop_url: Optional[str] = None
    exceeded_max_hops: bool = False
    visited: List[str] = field(default_factory=list)
    error: Optional[str] = None


async def check_redirect_loops(
    client: httpx.AsyncClient,
    links: List[Link],
    max_links: int = DEFAULT_MAX_LINKS_CHECKED,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    max_hops: int = MAX_HOPS,
) -> List[dict]:
    """
    Manually walks the redirect chain (one hop at a time, no
    auto-follow) for a deduped sample of `links`, looking for a URL
    that reappears — a genuine loop — versus a chain that simply runs
    past `max_hops` without one. Results are per-URL — a link repeated
    on the page is only checked once.
    """
    candidates = _dedupe_checkable(links)
    sample = candidates[:max_links]
    if not sample:
        return []

    semaphore = asyncio.Semaphore(max(1, concurrency))
    results = await asyncio.gather(
        *(_walk_one(client, semaphore, link.url, timeout, max_hops) for link in sample)
    )

    findings: List[dict] = []
    findings += _check_loops(results)
    findings += _check_runaway_chains(results)

    if len(candidates) > max_links:
        logger.debug("links.loops: link sample truncated by max_links cap")

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


async def _walk_one(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, start_url: str, timeout: float, max_hops: int
) -> LoopCheckResult:
    async with semaphore:
        visited: List[str] = []
        current = start_url

        for _ in range(max_hops):
            visited.append(current)
            try:
                response = await client.get(current, timeout=timeout, follow_redirects=False)
            except httpx.HTTPError as exc:
                return LoopCheckResult(original_url=start_url, visited=visited, error=str(exc))

            if response.status_code not in REDIRECT_STATUS_CODES:
                return LoopCheckResult(original_url=start_url, visited=visited)  # terminated normally

            location = response.headers.get("location")
            if not location:
                return LoopCheckResult(original_url=start_url, visited=visited)  # malformed redirect, treat as terminal

            next_url = str(httpx.URL(current).join(location))
            if next_url in visited:
                return LoopCheckResult(
                    original_url=start_url, is_loop=True, loop_url=next_url, visited=visited + [next_url],
                )
            current = next_url

        return LoopCheckResult(original_url=start_url, exceeded_max_hops=True, visited=visited)


def _check_loops(results: List[LoopCheckResult]) -> List[dict]:
    loops = [r for r in results if r.is_loop]
    if not loops:
        return []

    examples = ", ".join(f"{r.original_url} (cycles back to {r.loop_url})" for r in loops[:MAX_EXAMPLES])
    return [_finding(
        "critical",
        "Redirect loop detected",
        f"{len(loops)} link(s) redirect in a genuine cycle that never reaches a final page: "
        f"{examples}. Anyone following the link — human or crawler — gets stuck bouncing "
        "between the same URLs indefinitely; browsers will eventually show an error.",
        recommendation="Trace the redirect rule chain at the server/CDN level and fix "
                        "whichever rule points back at an earlier URL in the chain.",
    )]


def _check_runaway_chains(results: List[LoopCheckResult]) -> List[dict]:
    runaway = [r for r in results if r.exceeded_max_hops]
    if not runaway:
        return []

    examples = ", ".join(r.original_url for r in runaway[:MAX_EXAMPLES])
    return [_finding(
        "warning",
        "Redirect chain exceeds a sane hop limit",
        f"{len(runaway)} link(s) were still redirecting after {MAX_HOPS} hops without "
        f"revisiting a prior URL: {examples}. Whether or not it's a true cycle, a chain this "
        "long is unreasonable and costly for every visitor to walk.",
        recommendation="Shorten the redirect chain to point as directly as possible at the "
                        "final destination.",
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
