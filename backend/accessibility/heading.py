"""
accessibility/heading.py

Heading-outline checks framed around assistive-tech navigation (WCAG
1.3.1 "Info and Relationships", 2.4.6 "Headings and Labels") rather
than SEO relevance: seo/headings.py already covers missing/duplicate H1
and skipped levels for topical-signal reasons, and module="seo" there
is the version of that check that feeds the SEO score — this module
covers what's specific to screen readers: headings with no announcable
text at all (screen readers announce "heading level N" and then
nothing), and heading elements used purely for visual styling of
non-heading content. Reads crawler.parser.ParsedPage.soup directly
since empty/icon-only headings aren't visible in the already-extracted
`headings` text-only dict.
"""

from __future__ import annotations

from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "accessibility"
CATEGORY = "headings"

HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
MAX_EXAMPLES = 5


def check_heading_structure(page: ParsedPage) -> List[dict]:
    """Findings for heading-outline issues that specifically affect assistive tech."""
    soup = page.soup
    findings: List[dict] = []

    findings += _check_empty_headings(page, soup)
    findings += _check_skipped_levels(page)
    findings += _check_no_headings_at_all(page)

    return findings


def _check_empty_headings(page: ParsedPage, soup) -> List[dict]:
    empty = []
    for tag_name in HEADING_TAGS:
        for tag in soup.find_all(tag_name):
            if _accessible_text(tag):
                continue
            empty.append(tag_name)

    if not empty:
        return []
    return [_finding(
        "warning",
        "Heading with no accessible text",
        f"{page.url} has {len(empty)} heading element(s) (e.g. <{empty[0]}>) with no text "
        "content, aria-label, or alt text on a contained image. Screen readers announce "
        "\"heading level N\" and then nothing, a confusing dead stop when navigating by "
        "heading (a common screen-reader shortcut).",
        recommendation="Give every heading real text content, or remove the heading tag if "
                        "the element isn't actually introducing a section.",
    )]


def _accessible_text(tag) -> bool:
    if tag.get_text(strip=True):
        return True
    if tag.get("aria-label") and tag["aria-label"].strip():
        return True
    for img in tag.find_all("img"):
        if (img.get("alt") or "").strip():
            return True
    return False


def _check_skipped_levels(page: ParsedPage) -> List[dict]:
    headings = page.headings or {}
    if not _order_is_sequential(headings):
        return [_finding(
            "warning",
            "Heading levels skip a level",
            f"{page.url} uses a deeper heading level without one of the levels above it "
            "present. Screen reader users navigating by heading level build a mental outline "
            "from the levels alone — a skipped level reads as a broken or missing section.",
            recommendation="Restructure headings so each level nests under the one directly "
                            "above it — H1 then H2 then H3, without skipping — even if that "
                            "means changing visual size independently via CSS.",
        )]
    return []


def _order_is_sequential(headings) -> bool:
    seen_any = False
    for i, level in enumerate(HEADING_TAGS):
        if headings.get(level):
            seen_any = True
        elif seen_any and any(headings.get(deeper) for deeper in HEADING_TAGS[i + 1:]):
            return False
    return True


def _check_no_headings_at_all(page: ParsedPage) -> List[dict]:
    headings = page.headings or {}
    if any(headings.get(level) for level in HEADING_TAGS):
        return []
    if page.word_count < 50:
        return []  # not enough content for an outline to matter (e.g. a redirect/error page)
    return [_finding(
        "info",
        "No headings on a content-heavy page",
        f"{page.url} has {page.word_count} words of content but zero heading elements. "
        "Screen reader users rely on headings to jump between sections instead of reading "
        "everything linearly; with none present, the only option is a slow top-to-bottom read.",
        recommendation="Add heading elements (H1 for the page topic, H2+ for sections) that "
                        "mirror the page's actual content structure.",
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
