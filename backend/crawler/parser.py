"""
crawler/parser.py

Turns raw HTML into a structured, network-free ParsedPage. Every other
module in this package (links.py, extractor.py) consumes a ParsedPage
instead of re-parsing HTML itself, so BeautifulSoup only runs once per
fetched page no matter how many downstream checks look at it.

Kept dependency-light on purpose: this module never makes a network
call and never knows about httpx/asyncio — crawler.py owns fetching,
this module only owns turning bytes-already-in-hand into structure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup, Tag

from config.logging import logger

HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
NOISE_TAGS = ("script", "style", "noscript", "template")


@dataclass
class ParsedPage:
    """
    Structured view of one fetched page. `soup` is kept around so a
    caller can do a one-off custom lookup, but every field that
    links.py/extractor.py need is already pulled out below so most
    callers never have to touch BeautifulSoup directly.
    """

    url: str
    soup: BeautifulSoup

    title: Optional[str] = None
    meta: Dict[str, str] = field(default_factory=dict)  # name/property (lowercased) -> content
    headings: Dict[str, List[str]] = field(default_factory=dict)  # "h1" -> [text, ...]

    anchor_tags: List[Tag] = field(default_factory=list)
    image_tags: List[Tag] = field(default_factory=list)

    canonical: Optional[str] = None
    lang: Optional[str] = None
    json_ld: List[Any] = field(default_factory=list)

    text_content: str = ""
    word_count: int = 0
    html_bytes: int = 0


def parse_html(url: str, html: str) -> ParsedPage:
    """Parse one page's raw HTML into a ParsedPage. Never raises on malformed markup."""
    soup = BeautifulSoup(html or "", "lxml")

    page = ParsedPage(url=url, soup=soup, html_bytes=len(html.encode("utf-8", errors="ignore")))
    page.title = _extract_title(soup)
    page.meta = _extract_meta(soup)
    page.headings = _extract_headings(soup)
    page.anchor_tags = soup.find_all("a")
    page.image_tags = soup.find_all("img")
    page.canonical = _extract_canonical(soup)
    page.lang = _extract_lang(soup)
    page.json_ld = _extract_json_ld(url, soup)
    page.text_content = _extract_visible_text(soup)
    page.word_count = len(page.text_content.split())

    return page


def _extract_title(soup: BeautifulSoup) -> Optional[str]:
    tag = soup.find("title")
    if not tag or not tag.string:
        return None
    return tag.get_text(strip=True) or None


def _extract_meta(soup: BeautifulSoup) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    for tag in soup.find_all("meta"):
        key = tag.get("name") or tag.get("property")
        content = tag.get("content")
        if key and content is not None:
            meta[key.strip().lower()] = content.strip()
    return meta


def _extract_headings(soup: BeautifulSoup) -> Dict[str, List[str]]:
    headings: Dict[str, List[str]] = {tag: [] for tag in HEADING_TAGS}
    for tag_name in HEADING_TAGS:
        for tag in soup.find_all(tag_name):
            text = tag.get_text(strip=True)
            if text:
                headings[tag_name].append(text)
    return headings


def _extract_canonical(soup: BeautifulSoup) -> Optional[str]:
    for tag in soup.find_all("link"):
        rel = tag.get("rel") or []
        rel = [rel] if isinstance(rel, str) else rel
        if any(r.lower() == "canonical" for r in rel) and tag.get("href"):
            return tag["href"].strip()
    return None


def _extract_lang(soup: BeautifulSoup) -> Optional[str]:
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        return html_tag["lang"].strip()
    return None


def _extract_json_ld(url: str, soup: BeautifulSoup) -> List[Any]:
    """Parses every <script type="application/ld+json"> block; skips ones that don't parse."""
    blocks: List[Any] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text()
        if not raw or not raw.strip():
            continue
        try:
            blocks.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.debug(f"parser.py: skipping malformed JSON-LD on {url}: {exc}")
    return blocks


def _extract_visible_text(soup: BeautifulSoup) -> str:
    """Best-effort visible-text extraction: strips script/style/template content first."""
    working = BeautifulSoup(str(soup), "lxml")
    for tag in working(NOISE_TAGS):
        tag.decompose()
    text = working.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()
