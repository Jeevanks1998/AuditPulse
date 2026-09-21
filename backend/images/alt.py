"""
images/alt.py

Context-appropriateness checks for alt text, distinct from
seo/alt_text.py's presence/length/filename checks: redundant phrasing
that screen readers already announce for free ("image of...", "photo
of..." — screen readers already say "image" or "graphic" before
reading alt text, so restating it is noise), and a linked image with
no visible link text where the alt text duplicates the link's own
destination context rather than describing the image itself. Reads
crawler.parser.ParsedPage.image_tags, the same <img> tag list
seo/alt_text.py uses.
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "images"
CATEGORY = "alt"

_REDUNDANT_PREFIX_RE = re.compile(
    r"^(image|photo|picture|graphic|icon|logo)\s+(of|showing|depicting)\b", re.IGNORECASE
)
MAX_EXAMPLES = 5


def check_alt_text_quality(page: ParsedPage) -> List[dict]:
    """Findings for redundant alt-text phrasing and decorative icons using non-empty alt."""
    images = page.image_tags or []
    if not images:
        return []

    findings: List[dict] = []
    findings += _check_redundant_phrasing(page, images)
    findings += _check_decorative_icon_in_labeled_link(page)
    return findings


def _check_redundant_phrasing(page: ParsedPage, images: list) -> List[dict]:
    redundant = []
    for img in images:
        alt = (img.get("alt") or "").strip()
        if alt and _REDUNDANT_PREFIX_RE.match(alt):
            redundant.append(alt)

    if not redundant:
        return []

    examples = ", ".join(f"\"{a}\"" for a in redundant[:MAX_EXAMPLES])
    return [_finding(
        "info",
        "Alt text starts with a redundant \"image of\" phrase",
        f"{page.url} has {len(redundant)} image(s) with alt text starting with a phrase "
        f"like \"image of\" or \"photo of\": {examples}. Screen readers already announce an "
        "element as an image before reading its alt text, so restating that adds noise "
        "without adding information.",
        recommendation="Drop the redundant lead-in and describe what's in the image "
                        "directly, e.g. \"Golden retriever running on a beach\" instead of "
                        "\"Image of a golden retriever running on a beach\".",
    )]


def _check_decorative_icon_in_labeled_link(page: ParsedPage) -> List[dict]:
    """
    An <img> inside an <a> that already has other visible text doesn't
    need its own descriptive alt — the link text already tells a
    screen reader where the link goes, so a separately-worded alt on
    the icon is usually redundant with (and can even contradict) the
    link's own accessible name.
    """
    offenders = []
    for link in page.soup.find_all("a"):
        visible_text = link.get_text(strip=True)
        if not visible_text:
            continue  # icon-only link: the img's alt is the link's only accessible name, leave it
        for img in link.find_all("img"):
            alt = (img.get("alt") or "").strip()
            if alt and alt.lower() not in visible_text.lower() and len(alt) > 3:
                offenders.append(alt)

    if not offenders:
        return []

    examples = ", ".join(f"\"{a}\"" for a in offenders[:MAX_EXAMPLES])
    return [_finding(
        "info",
        "Icon alt text duplicates or conflicts with adjacent link text",
        f"{page.url} has {len(offenders)} image(s) inside a link that already has its own "
        f"visible text, where the image's alt text describes something different from that "
        f"link text: {examples}. A screen reader announces both, which can be confusing or "
        "redundant when the icon is purely decorative alongside a labeled link.",
        recommendation="If the icon is purely decorative next to existing link text, set "
                        "alt=\"\" on it; if it conveys extra meaning the link text doesn't, "
                        "make sure the two don't contradict each other.",
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
