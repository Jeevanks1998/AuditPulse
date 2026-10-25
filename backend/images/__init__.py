"""
Image checks (not used by the audit pipeline yet):
  optimizer   - modern formats (webp/avif) and width/height set
  alt         - alt text that repeats "image of..." or the link text
  lazyload    - lazy loading used, but not on the first image
  broken      - missing src, and a sample of image URLs checked live
  image_score - 0-100 score
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
    """Checks that only need the parsed page."""
    findings: List[dict] = []
    findings += check_image_optimization(page)
    findings += check_alt_text_quality(page)
    findings += check_lazy_loading(page)
    findings += check_missing_src(page)
    return findings


async def run_site_checks(client: httpx.AsyncClient, page: ParsedPage) -> List[dict]:
    """Checks a sample of the page's image URLs live."""
    return await check_broken_images(client, page)
