"""
images/optimizer.py

Static, markup-only optimization signals: whether any image on the
page uses a next-gen format (webp/avif, or <picture> with a
next-gen <source>) instead of only legacy jpg/png/gif, and whether
images omit explicit width/height (or an aspect-ratio style), which
lets the browser reserve layout space before the image loads instead
of shifting content once it arrives (a direct Cumulative Layout Shift
contributor). Reads crawler.parser.ParsedPage.image_tags, the same
<img> tag list seo/alt_text.py uses.
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "images"
CATEGORY = "optimization"

_NEXT_GEN_EXTENSION_RE = re.compile(r"\.(webp|avif)(\?|#|$)", re.IGNORECASE)
_LEGACY_EXTENSION_RE = re.compile(r"\.(jpe?g|png|gif|bmp)(\?|#|$)", re.IGNORECASE)
MIN_LEGACY_IMAGES_TO_FLAG = 3
MAX_EXAMPLES = 5


def check_image_optimization(page: ParsedPage) -> List[dict]:
    """Findings for missing next-gen formats and missing width/height on images."""
    images = page.image_tags or []
    if not images:
        return []

    findings: List[dict] = []
    findings += _check_next_gen_formats(page, images)
    findings += _check_missing_dimensions(page, images)
    return findings


def _check_next_gen_formats(page: ParsedPage, images: list) -> List[dict]:
    if _page_has_next_gen_source(page):
        return []

    legacy = [img for img in images if _LEGACY_EXTENSION_RE.search(img.get("src") or "")]
    if len(legacy) < MIN_LEGACY_IMAGES_TO_FLAG:
        return []

    return [_finding(
        "info",
        "No next-gen image formats in use",
        f"{page.url} has {len(legacy)} image(s) in legacy formats (JPEG/PNG/GIF) and no "
        "WebP or AVIF source anywhere on the page (directly or via <picture>/<source>). "
        "Next-gen formats typically produce meaningfully smaller files at equivalent visual "
        "quality.",
        recommendation="Serve WebP or AVIF (with a <picture><source> fallback to JPEG/PNG "
                        "for older clients, or a CDN that content-negotiates format "
                        "automatically).",
    )]


def _page_has_next_gen_source(page: ParsedPage) -> bool:
    for img in page.image_tags or []:
        if _NEXT_GEN_EXTENSION_RE.search(img.get("src") or ""):
            return True
    for source in page.soup.find_all("source"):
        srcset = source.get("srcset") or ""
        type_attr = (source.get("type") or "").lower()
        if "image/webp" in type_attr or "image/avif" in type_attr or _NEXT_GEN_EXTENSION_RE.search(srcset):
            return True
    return False


def _check_missing_dimensions(page: ParsedPage, images: list) -> List[dict]:
    missing = []
    for img in images:
        if img.get("width") and img.get("height"):
            continue
        style = img.get("style") or ""
        if "aspect-ratio" in style:
            continue
        missing.append(img.get("src") or img.get("alt") or "<img>")

    if not missing:
        return []

    total = len(images)
    severity = "warning" if len(missing) == total else "info"
    examples = ", ".join(missing[:MAX_EXAMPLES])
    return [_finding(
        severity,
        "Images missing width/height attributes",
        f"{len(missing)} of {total} image(s) on {page.url} have no width/height attributes "
        f"(or aspect-ratio style): {examples}. Without a reserved size, the browser doesn't "
        "know how much space to leave for the image before it loads, so surrounding content "
        "jumps once it arrives — a direct Cumulative Layout Shift contributor.",
        recommendation="Add width and height attributes (or a CSS aspect-ratio) matching "
                        "the image's intrinsic size so the browser can reserve layout space "
                        "up front.",
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
