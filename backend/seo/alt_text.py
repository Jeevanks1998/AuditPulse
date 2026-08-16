"""
seo/alt_text.py

Page-level image alt-text checks: missing alt attributes (an
accessibility issue that also costs image-search visibility), alt text
that's just a filename, and alt text so long it reads more like a
caption than a description. Reads crawler.parser.ParsedPage.image_tags,
the raw <img> tag list the shared parser already collected.

crawler/extractor.py has a coarser version of the missing-alt count for
its accessibility score; this module goes further (filename-sniffing,
length) and is the version to prefer once seo/ is wired into the
pipeline.
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "seo"
CATEGORY = "images"

ALT_MAX_LEN = 125
FILENAME_ALT_PATTERN = re.compile(r"^[\w-]+\.(jpe?g|png|gif|webp|svg|bmp)$", re.IGNORECASE)


def check_alt_text(page: ParsedPage) -> List[dict]:
    """Findings for the alt text on one page's images."""
    images = page.image_tags or []
    if not images:
        return []

    findings: List[dict] = []
    missing = 0
    filename_alts = 0
    long_alts = 0

    for img in images:
        alt = img.get("alt")
        if alt is None:
            missing += 1
            continue
        alt = alt.strip()
        if not alt:
            continue  # alt="" is valid for decorative images, not a finding
        if FILENAME_ALT_PATTERN.match(alt):
            filename_alts += 1
        elif len(alt) > ALT_MAX_LEN:
            long_alts += 1

    total = len(images)
    if missing:
        severity = "critical" if missing == total else "warning"
        findings.append(_finding(
            severity,
            "Images missing alt attribute",
            f"{missing} of {total} images on {page.url} have no alt attribute at all "
            "(different from alt=\"\", which is a valid way to mark an image decorative). "
            "Screen readers announce the filename or nothing, and search engines have no "
            "text to associate with the image.",
            recommendation="Add a descriptive alt attribute to every meaningful image, and "
                            "alt=\"\" only for purely decorative ones.",
        ))

    if filename_alts:
        findings.append(_finding(
            "info",
            "Alt text is just a filename",
            f"{filename_alts} image(s) on {page.url} have alt text that's just a filename "
            "(e.g. \"img_2043.jpg\"), which describes nothing about the image content.",
            recommendation="Replace filename alt text with a short description of what the "
                            "image shows.",
        ))

    if long_alts:
        findings.append(_finding(
            "info",
            "Alt text is very long",
            f"{long_alts} image(s) on {page.url} have alt text over {ALT_MAX_LEN} characters, "
            "closer to a caption than a description.",
            recommendation=f"Keep alt text under roughly {ALT_MAX_LEN} characters; move "
                            "longer context into surrounding page text or a caption.",
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
