"""
seo/headings.py

Page-level heading-structure checks: exactly one H1, no skipped levels
(e.g. an H3 appearing with no H1/H2 above it), and headings used as
styling rather than structure (very short or all-caps/punctuation-only
text). Reads crawler.parser.ParsedPage.headings, a level -> [text, ...]
dict already built by the shared parser.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from crawler.parser import ParsedPage

MODULE = "seo"
CATEGORY = "headings"

HEADING_ORDER = ("h1", "h2", "h3", "h4", "h5", "h6")
MIN_MEANINGFUL_HEADING_LEN = 3


def check_headings(page: ParsedPage) -> List[dict]:
    """Findings for one page's heading outline."""
    findings: List[dict] = []
    headings = page.headings or {}

    h1s = headings.get("h1", [])
    if len(h1s) == 0:
        findings.append(_finding(
            "warning",
            "Missing H1",
            f"{page.url} has no H1 heading. The H1 is the strongest on-page signal of what "
            "the page is about, after the title tag.",
            recommendation="Add a single H1 that describes the page's main topic.",
        ))
    elif len(h1s) > 1:
        findings.append(_finding(
            "info",
            "Multiple H1 headings",
            f"{page.url} has {len(h1s)} H1 headings; most SEO guidance treats H1 as a "
            "one-per-page landmark, with H2/H3 for the rest of the outline.",
            recommendation="Keep exactly one H1 and demote the others to H2 or lower.",
        ))

    if not _order_is_sequential(headings):
        findings.append(_finding(
            "info",
            "Heading levels skip a level",
            f"{page.url} uses a deeper heading level (e.g. H3) without one of the levels "
            "above it (H1/H2) present, breaking the document outline assistive tech and "
            "search engines rely on.",
            recommendation="Restructure headings so each level nests under the one above it "
                            "without skipping — H1 then H2 then H3, in order.",
        ))

    thin_headings = [
        (level, text) for level in HEADING_ORDER for text in headings.get(level, [])
        if len(text.strip()) < MIN_MEANINGFUL_HEADING_LEN
    ]
    if thin_headings:
        findings.append(_finding(
            "info",
            "Very short heading text",
            f"{page.url} has {len(thin_headings)} heading(s) under "
            f"{MIN_MEANINGFUL_HEADING_LEN} characters (e.g. \"{thin_headings[0][1]}\"), which "
            "carries little topical signal and may indicate a heading used purely for "
            "visual styling.",
            recommendation="Reserve heading tags for real section titles; use styled <span>/"
                            "<div> text for purely decorative labels.",
        ))

    return findings


def _order_is_sequential(headings: Dict[str, List[str]]) -> bool:
    """True unless a level appears while every level above it is empty."""
    seen_any = False
    for i, level in enumerate(HEADING_ORDER):
        if headings.get(level):
            seen_any = True
        elif seen_any and any(headings.get(deeper) for deeper in HEADING_ORDER[i + 1:]):
            return False
    return True


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
