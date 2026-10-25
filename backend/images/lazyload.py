"""
Lazy loading: flags image-heavy pages using none, and a lazy-loaded first image (slows the main image).
"""

from __future__ import annotations

from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "images"
CATEGORY = "lazyload"

MIN_IMAGES_TO_EXPECT_LAZY_LOADING = 8


def check_lazy_loading(page: ParsedPage) -> List[dict]:
    """Findings for a page with no lazy-loaded images, and for an eagerly-needed first image marked lazy."""
    images = page.image_tags or []
    if not images:
        return []

    findings: List[dict] = []
    findings += _check_no_lazy_loading_used(page, images)
    findings += _check_first_image_lazy(page, images)
    return findings


def _check_no_lazy_loading_used(page: ParsedPage, images: list) -> List[dict]:
    if len(images) < MIN_IMAGES_TO_EXPECT_LAZY_LOADING:
        return []

    lazy_count = sum(1 for img in images if (img.get("loading") or "").lower() == "lazy")
    if lazy_count > 0:
        return []

    return [_finding(
        "warning",
        "No images use native lazy loading",
        f"{page.url} has {len(images)} images and none use loading=\"lazy\". Every image on "
        "the page competes for bandwidth during initial load regardless of whether it's ever "
        "scrolled into view.",
        recommendation="Add loading=\"lazy\" to images that render below the fold, leaving "
                        "the first (likely above-the-fold) image or two eager so they don't "
                        "delay LCP.",
    )]


def _check_first_image_lazy(page: ParsedPage, images: list) -> List[dict]:
    first = images[0]
    if (first.get("loading") or "").lower() != "lazy":
        return []

    return [_finding(
        "warning",
        "First image on the page is lazy-loaded",
        f"{page.url}'s first <img> in document order has loading=\"lazy\". This image is the "
        "one most likely to be above the fold and the Largest Contentful Paint element — "
        "lazy-loading it defers its fetch instead of prioritizing it, which typically hurts "
        "LCP rather than page performance overall.",
        recommendation="Remove loading=\"lazy\" from the first/hero image (and consider "
                        "fetchpriority=\"high\" on it instead); reserve lazy loading for "
                        "images further down the page.",
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
