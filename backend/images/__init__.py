"""
images/

A dedicated, granular image-quality check package — one file per
concern — for an "images" score that doesn't exist yet anywhere in the
pipeline (same situation ux/, mobile/, and forms/ describe: no
`breakdown["images"] = ...` placeholder currently sitting in
services.audit_service.run_audit_pipeline to replace, so wiring this
in means adding an "images" key to breakdown/EMPTY_BREAKDOWN rather
than swapping one out). Every check function returns findings in the
same {module, category, severity, title, description, recommendation}
shape services.audit_service / models.issue already persist, so it
plugs into Issue sync / report.html / history exactly like every other
module here.

Distinct from seo/alt_text.py, which checks alt-text presence/length/
filename-sniffing for SEO purposes:

    optimizer   — next-gen format (webp/avif) usage; missing width/
                  height causing layout shift
    alt         — context-appropriateness of alt text (redundant
                  "image of..." phrasing; icon alt duplicating
                  adjacent link text) rather than presence/length
    lazyload    — native loading="lazy" usage: none used on an
                  image-heavy page, or used on the likely-LCP first
                  image
    broken      — missing src attributes (sync), plus a live-checked
                  sample of <img> src URLs for 4xx/5xx/connection
                  errors (async, needs an httpx.AsyncClient)
    image_score — turns any list of these findings into a weighted
                  0-100 score with a per-category breakdown

Usage — wiring this into the real pipeline (crawler.crawler.Crawler
already produces a ParsedPage per page):

    from images import run_page_checks, run_site_checks, score_images

    page_findings = run_page_checks(page)
    site_findings = await run_site_checks(client, page)
    result = score_images(page_findings + site_findings)
"""

from __future__ import annotations

from typing import List

import httpx

from crawler.parser import ParsedPage

from images.alt import check_alt_text_quality
from images.broken import check_broken_images, check_missing_src
from images.image_score import ImageScoreResult, score_images
from images.lazyload import check_lazy_loading
from images.optimizer import check_image_optimization

__all__ = [
    "check_image_optimization",
    "check_alt_text_quality",
    "check_lazy_loading",
    "check_missing_src",
    "check_broken_images",
    "score_images",
    "ImageScoreResult",
    "run_page_checks",
    "run_site_checks",
]


def run_page_checks(page: ParsedPage) -> List[dict]:
    """
    Every check that only needs one already-fetched page: optimization,
    alt-text quality, lazy-loading, and the zero-request missing-src
    check. Cheap and synchronous — safe to call once per page during a
    crawl, same as seo/accessibility/ux's page-level checks.
    """
    findings: List[dict] = []
    findings += check_image_optimization(page)
    findings += check_alt_text_quality(page)
    findings += check_lazy_loading(page)
    findings += check_missing_src(page)
    return findings


async def run_site_checks(client: httpx.AsyncClient, page: ParsedPage) -> List[dict]:
    """
    The one images/ check that makes its own requests: a live-checked
    sample of this page's image src URLs. Call once per page (or just
    for the homepage, for a cheaper audit) — same shape as
    seo.run_site_checks.
    """
    return await check_broken_images(client, page)
