"""
seo/

A dedicated, granular SEO-check package — one file per concern — that
supersedes the handful of SEO rules currently inlined in
crawler/extractor.py::_build_findings. Every check function returns
findings in the same {module, severity, title, description,
recommendation} shape services.audit_service / models.issue already
persist, so nothing downstream (Issue sync, report.html, history)
needs to change to consume them.

Two kinds of checks live here:

Page-level (take a crawler.parser.ParsedPage, and sometimes the page's
crawler.links.Link list):
    title, meta, headings, canonical, schema, open_graph,
    twitter_cards, alt_text

Site-level (async, need an httpx.AsyncClient because they make their
own requests — robots.txt, sitemap files, and a sample of links):
    sitemap, robots, broken_links

`seo_score.py` turns any list of these findings into a weighted 0-100
score with a per-category breakdown, the same shape as
Audit.breakdown / AuditStatsOut.breakdown already use for "seo".

Usage — wiring this into the real pipeline (crawler.crawler.Crawler
already produces ParsedPage + Link[] per page; this replaces the SEO
portion of extract_signals' findings, it doesn't replace the whole
crawl):

    from seo import run_page_checks, run_site_checks, score_seo

    page_findings = run_page_checks(page, links)
    site_findings = await run_site_checks(client, base_url, robots_sitemaps=declared)
    all_findings = page_findings + site_findings
    result = score_seo(all_findings)
"""

from __future__ import annotations

from typing import List, Optional

import httpx

from crawler.links import Link
from crawler.parser import ParsedPage

from seo.alt_text import check_alt_text
from seo.broken_links import check_broken_links
from seo.canonical import check_canonical
from seo.headings import check_headings
from seo.meta import check_meta
from seo.open_graph import check_open_graph
from seo.robots import check_robots
from seo.schema import check_structured_data
from seo.seo_score import SEOScoreResult, score_seo
from seo.sitemap import check_sitemap
from seo.title import check_duplicate_titles, check_title
from seo.twitter_cards import check_twitter_cards

__all__ = [
    "check_title",
    "check_duplicate_titles",
    "check_meta",
    "check_headings",
    "check_canonical",
    "check_structured_data",
    "check_open_graph",
    "check_twitter_cards",
    "check_alt_text",
    "check_sitemap",
    "check_robots",
    "check_broken_links",
    "score_seo",
    "SEOScoreResult",
    "run_page_checks",
    "run_site_checks",
]


def run_page_checks(page: ParsedPage, links: Optional[List[Link]] = None) -> List[dict]:
    """
    Every check that only needs one already-fetched page. Cheap and
    synchronous — safe to call once per page during a crawl.
    """
    findings: List[dict] = []
    findings += check_title(page)
    findings += check_meta(page)
    findings += check_headings(page)
    findings += check_canonical(page)
    findings += check_structured_data(page)
    findings += check_open_graph(page)
    findings += check_twitter_cards(page)
    findings += check_alt_text(page)
    return findings


async def run_site_checks(
    client: httpx.AsyncClient,
    base_url: str,
    robots_sitemaps: Optional[List[str]] = None,
    links_to_verify: Optional[List[Link]] = None,
) -> List[dict]:
    """
    Everything that needs its own HTTP requests: robots.txt, sitemap
    file(s), and (optionally) a live check of a sample of on-page links.
    Call this once per crawl, not once per page.
    """
    findings: List[dict] = []
    findings += await check_robots(client, base_url)
    findings += await check_sitemap(client, base_url, known_sitemaps=robots_sitemaps)
    if links_to_verify:
        findings += await check_broken_links(client, links_to_verify)
    return findings
