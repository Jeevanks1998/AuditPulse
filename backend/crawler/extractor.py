"""
crawler/extractor.py

Turns a ParsedPage (crawler.parser) plus its resolved Link[] (crawler.links)
into PageSignals — the flat, JSON-friendly dict of measurements the SEO /
accessibility scoring in services.audit_service actually reads, rather
than the random `breakdown` scores the placeholder pipeline generates
today. Also produces a list of {module, severity, title, description}
finding dicts in the same shape services.audit_service._generate_
placeholder_findings already writes, so wiring this in only means
replacing where those findings come from, not the storage layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from crawler.links import Link
from crawler.parser import ParsedPage

TITLE_MIN_LEN, TITLE_MAX_LEN = 30, 60
META_DESC_MIN_LEN, META_DESC_MAX_LEN = 70, 160
THIN_CONTENT_WORD_COUNT = 200


@dataclass
class PageSignals:
    url: str

    title: Optional[str] = None
    title_length: int = 0
    meta_description: Optional[str] = None
    meta_description_length: int = 0
    canonical: Optional[str] = None
    lang: Optional[str] = None

    h1_count: int = 0
    heading_order_ok: bool = True
    word_count: int = 0

    images_total: int = 0
    images_missing_alt: int = 0

    internal_links: int = 0
    external_links: int = 0
    nofollow_links: int = 0

    has_viewport_meta: bool = False
    has_json_ld: bool = False
    has_open_graph: bool = False

    findings: List[Dict[str, Any]] = field(default_factory=list)


def extract_signals(page: ParsedPage, links: List[Link]) -> PageSignals:
    """Builds PageSignals for one page and attaches the SEO/accessibility findings it implies."""
    signals = PageSignals(url=page.url)

    signals.title = page.title
    signals.title_length = len(page.title) if page.title else 0
    signals.meta_description = page.meta.get("description")
    signals.meta_description_length = len(signals.meta_description) if signals.meta_description else 0
    signals.canonical = page.canonical
    signals.lang = page.lang

    signals.h1_count = len(page.headings.get("h1", []))
    signals.heading_order_ok = _heading_order_ok(page.headings)
    signals.word_count = page.word_count

    signals.images_total = len(page.image_tags)
    signals.images_missing_alt = sum(
        1 for img in page.image_tags if not (img.get("alt") or "").strip()
    )

    signals.internal_links = sum(1 for link in links if link.is_internal)
    signals.external_links = sum(1 for link in links if not link.is_internal)
    signals.nofollow_links = sum(1 for link in links if link.nofollow)

    signals.has_viewport_meta = "viewport" in page.meta
    signals.has_json_ld = bool(page.json_ld)
    signals.has_open_graph = any(key.startswith("og:") for key in page.meta)

    signals.findings = _build_findings(signals)
    return signals


def _heading_order_ok(headings: Dict[str, List[str]]) -> bool:
    """True unless a heading level appears while every level above it is empty (e.g. h3 with no h1/h2)."""
    order = ["h1", "h2", "h3", "h4", "h5", "h6"]
    seen_any = False
    for level in order:
        if headings.get(level):
            seen_any = True
        elif seen_any and any(headings.get(deeper) for deeper in order[order.index(level) + 1:]):
            return False
    return True


def _build_findings(s: PageSignals) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []

    def add(module: str, severity: str, title: str, description: str) -> None:
        findings.append({"module": module, "severity": severity, "title": title, "description": description})

    # --- SEO ---
    if not s.title:
        add("seo", "critical", "Missing <title>", f"{s.url} has no <title> tag.")
    elif not (TITLE_MIN_LEN <= s.title_length <= TITLE_MAX_LEN):
        add(
            "seo", "warning", "Title length outside recommended range",
            f"Title is {s.title_length} characters; aim for {TITLE_MIN_LEN}-{TITLE_MAX_LEN}.",
        )

    if not s.meta_description:
        add("seo", "warning", "Missing meta description", f"{s.url} has no meta description tag.")
    elif not (META_DESC_MIN_LEN <= s.meta_description_length <= META_DESC_MAX_LEN):
        add(
            "seo", "info", "Meta description length outside recommended range",
            f"Meta description is {s.meta_description_length} characters; aim for "
            f"{META_DESC_MIN_LEN}-{META_DESC_MAX_LEN}.",
        )

    if not s.canonical:
        add("seo", "info", "Missing canonical link", f"{s.url} has no rel=canonical link tag.")

    if s.h1_count == 0:
        add("seo", "warning", "Missing H1", f"{s.url} has no H1 heading.")
    elif s.h1_count > 1:
        add("seo", "info", "Multiple H1 headings", f"{s.url} has {s.h1_count} H1 headings; expected exactly one.")

    if s.word_count < THIN_CONTENT_WORD_COUNT:
        add(
            "seo", "info", "Thin content",
            f"{s.url} has only {s.word_count} words of visible text (< {THIN_CONTENT_WORD_COUNT}).",
        )

    # --- Accessibility ---
    if not s.lang:
        add("accessibility", "warning", "Missing lang attribute", f"<html> on {s.url} has no lang attribute.")

    if s.images_total and s.images_missing_alt:
        add(
            "accessibility", "critical" if s.images_missing_alt == s.images_total else "warning",
            "Images missing alt text",
            f"{s.images_missing_alt} of {s.images_total} images on {s.url} have no alt attribute.",
        )

    if not s.heading_order_ok:
        add(
            "accessibility", "info", "Heading levels skip a level",
            f"{s.url} uses a deeper heading level without one of the levels above it present.",
        )

    if not s.has_viewport_meta:
        add("accessibility", "warning", "Missing viewport meta tag", f"{s.url} has no responsive viewport meta tag.")

    return findings
