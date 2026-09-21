"""
images/broken.py

Site-level check that actually requests a sample of a page's <img> src
URLs and reports which ones are broken (4xx/5xx) or erroring (timeout,
DNS, connection refused) — the images.py equivalent of
seo/broken_links.py, but for image sources rather than <a href>
targets, and also flagging <img> tags with no src at all (an empty or
missing src is a broken image with zero requests needed to know it).
Capped and concurrency-limited the same way seo/broken_links.py is, so
a page with many images doesn't turn one audit into dozens of extra
outbound requests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from config.logging import logger
from crawler.parser import ParsedPage

MODULE = "images"
CATEGORY = "broken"

DEFAULT_MAX_IMAGES_CHECKED = 30
DEFAULT_CONCURRENCY = 8
REQUEST_TIMEOUT_SECONDS = 8.0
MAX_EXAMPLES = 5


@dataclass
class ImageCheckResult:
    url: str
    status_code: Optional[int]
    ok: bool
    error: Optional[str] = None


def check_missing_src(page: ParsedPage) -> List[dict]:
    """Synchronous, zero-request check for <img> tags with no src attribute at all."""
    images = page.image_tags or []
    missing = [img for img in images if not (img.get("src") or "").strip()]
    if not missing:
        return []

    return [_finding(
        "critical",
        "Image tag has no src attribute",
        f"{page.url} has {len(missing)} of {len(images)} <img> tag(s) with no src (or an "
        "empty src), which renders as a broken-image icon in every browser with nothing to "
        "ever load.",
        recommendation="Set a valid src on every <img>, or remove the tag if it isn't "
                        "actually needed.",
    )]


async def check_broken_images(
    client: httpx.AsyncClient,
    page: ParsedPage,
    max_images: int = DEFAULT_MAX_IMAGES_CHECKED,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> List[dict]:
    """
    Live-checks a deduped sample of `page`'s <img> src URLs (resolved
    to absolute against page.url) and returns findings for anything
    broken or erroring. Results are per-URL, not per-occurrence — an
    image reused on the page is only checked once.
    """
    candidates = _dedupe_checkable(page)
    sample = candidates[:max_images]
    if not sample:
        return []

    semaphore = asyncio.Semaphore(max(1, concurrency))
    results = await asyncio.gather(
        *(_check_one(client, semaphore, url, timeout) for url in sample)
    )

    return _to_findings(page, results, truncated=len(candidates) > max_images)


def _dedupe_checkable(page: ParsedPage) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for img in page.image_tags or []:
        src = (img.get("src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        absolute = urljoin(page.url, src)
        if urlparse(absolute).scheme not in ("http", "https"):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(absolute)
    return out


async def _check_one(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, url: str, timeout: float) -> ImageCheckResult:
    async with semaphore:
        try:
            response = await client.head(url, timeout=timeout, follow_redirects=True)
            if response.status_code in (405, 501):
                response = await client.get(url, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as exc:
            return ImageCheckResult(url=url, status_code=None, ok=False, error=str(exc))

        return ImageCheckResult(url=url, status_code=response.status_code, ok=response.status_code < 400)


def _to_findings(page: ParsedPage, results: List[ImageCheckResult], truncated: bool) -> List[dict]:
    findings: List[dict] = []

    broken = [r for r in results if not r.ok and r.status_code is not None]
    errored = [r for r in results if r.error is not None]

    if broken:
        sample = ", ".join(f"{r.url} ({r.status_code})" for r in broken[:MAX_EXAMPLES])
        extra = f" and {len(broken) - MAX_EXAMPLES} more" if len(broken) > MAX_EXAMPLES else ""
        severity = "critical" if any((r.status_code or 0) >= 500 for r in broken) else "warning"
        findings.append(_finding(
            severity,
            "Broken image sources found",
            f"{len(broken)} image(s) on {page.url} returned an error status: {sample}{extra}.",
            recommendation="Fix the src URL or replace/remove the image so visitors don't "
                            "see a broken-image icon.",
        ))

    if errored:
        sample = ", ".join(r.url for r in errored[:MAX_EXAMPLES])
        extra = f" and {len(errored) - MAX_EXAMPLES} more" if len(errored) > MAX_EXAMPLES else ""
        findings.append(_finding(
            "warning",
            "Image sources failed to connect",
            f"{len(errored)} image URL(s) on {page.url} could not be reached at all "
            f"(timeout, DNS failure, or connection refused): {sample}{extra}.",
            recommendation="Verify these image URLs are correct and the hosting server is "
                            "reachable.",
        ))

    if truncated:
        logger.debug("images.broken: image sample truncated by max_images cap")

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
