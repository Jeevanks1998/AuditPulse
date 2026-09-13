"""
ux/

A dedicated, granular UX-check package — one file per concern — for a
"ux" score that doesn't exist yet anywhere in the pipeline (unlike
seo/accessibility/performance/security, there's no
`breakdown["ux"] = random.randint(...)` placeholder currently sitting
in services.audit_service.run_audit_pipeline to replace — wiring this
in means *adding* a "ux" key to breakdown/EMPTY_BREAKDOWN, not
swapping one out). Every check function returns findings in the same
{module, category, severity, title, description, recommendation} shape
services.audit_service / models.issue already persist, so it plugs
into Issue sync / report.html / history exactly like every other
module here.

Everything in this package is page-level and synchronous — no live
render or external API needed, since every check reads from
crawler.parser.ParsedPage (declared styles, markup structure, and
already-extracted visible text) rather than anything requiring a real
browser:

    navigation   — <nav> landmark, primary-link count, a way home,
                   breadcrumbs on nested pages
    typography   — declared body font size, line-height, font-family
                   sprawl
    colors       — declared color-palette size/reuse (not contrast —
                   see accessibility/contrast.py for the WCAG-ratio
                   check on the same markup)
    buttons      — generic/missing button labels, missing explicit
                   <button type="...">
    spacing      — crowded runs of adjacent interactive elements,
                   explicit zero-margin buttons/links
    readability  — Flesch Reading Ease on visible text, long unbroken
                   paragraphs
    ux_score     — turns any list of these findings into a weighted
                   0-100 score with a per-category breakdown

Usage — wiring this into the real pipeline (crawler.crawler.Crawler
already produces a ParsedPage per page):

    from ux import run_page_checks, score_ux

    findings = []
    for page in crawl_result.ok_pages:
        findings += run_page_checks(page.signals... )  # see note below

Note: run_page_checks takes a ParsedPage, not a PageSignals — crawler.
crawler.Crawler currently only hands extract_signals' PageSignals back
to callers, not the ParsedPage itself, so wiring this in for real also
means threading the ParsedPage (or the handful of fields ux/ actually
needs: soup, url, text_content, word_count, json_ld) through
crawler.crawler.PageResult the way security/mixed_content.py needs the
same thing.
"""

from __future__ import annotations

from typing import List

from crawler.parser import ParsedPage

from ux.buttons import check_buttons
from ux.colors import check_colors
from ux.navigation import check_navigation
from ux.readability import check_readability
from ux.spacing import check_spacing
from ux.typography import check_typography
from ux.ux_score import UxScoreResult, score_ux

__all__ = [
    "check_navigation",
    "check_typography",
    "check_colors",
    "check_buttons",
    "check_spacing",
    "check_readability",
    "score_ux",
    "UxScoreResult",
    "run_page_checks",
    "run_ux_checks",
]


def run_page_checks(page: ParsedPage) -> List[dict]:
    """
    Every UX check for one already-fetched, already-parsed page. Cheap
    and synchronous — safe to call once per page during a crawl, same
    as accessibility/seo's page-level checks.
    """
    findings: List[dict] = []
    findings += check_navigation(page)
    findings += check_typography(page)
    findings += check_colors(page)
    findings += check_buttons(page)
    findings += check_spacing(page)
    findings += check_readability(page)
    return findings


def run_ux_checks(pages: List[ParsedPage]) -> UxScoreResult:
    """
    Convenience entry point for a whole crawl: runs every page-level
    check across every page and scores the combined findings in one
    call. Pass a single-element list to score just the homepage.
    """
    findings: List[dict] = []
    for page in pages:
        findings += run_page_checks(page)
    return score_ux(findings)
