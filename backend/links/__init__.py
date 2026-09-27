"""
links/

A dedicated, granular link-quality check package — one file per
concern — for a "links" score that doesn't exist yet anywhere in the
pipeline (same situation ux/, mobile/, forms/, and images/ describe:
no `breakdown["links"] = ...` placeholder currently sitting in
services.audit_service.run_audit_pipeline to replace, so wiring this
in means adding a "links" key to breakdown/EMPTY_BREAKDOWN rather than
swapping one out). Every check function returns findings in the same
{module, category, severity, title, description, recommendation} shape
services.audit_service / models.issue already persist, so it plugs
into Issue sync / report.html / history exactly like every other
module here.

Distinct from seo/broken_links.py, which only checks whether a sample
of links returns a working status code:

    internal      — dead-end pages, nofollow on internal links, generic
                    anchor text ("click here")
    external      — target="_blank" without rel="noopener" (reverse
                    tabnabbing), links out to plain http, link-farm
                    volume
    redirects     — live-checked chain length, temporary vs. permanent
                    status codes, http links that never upgrade to
                    https (async, needs an httpx.AsyncClient)
    loops         — genuine redirect cycles vs. merely long chains,
                    found by manually walking hops rather than relying
                    on httpx's own TooManyRedirects (async)
    link_score    — turns any list of these findings into a weighted
                    0-100 score with a per-category breakdown

Usage — wiring this into the real pipeline (crawler.crawler.Crawler
already produces a ParsedPage + crawler.links.extract_links produces
its Link list per page):

    from links import run_page_checks, run_site_checks, score_links

    page_findings = run_page_checks(page, links)
    site_findings = await run_site_checks(client, links)
    result = score_links(page_findings + site_findings)
"""

from __future__ import annotations

from typing import List

import httpx

from crawler.links import Link
from crawler.parser import ParsedPage

from links.external import check_external_links
from links.internal import check_internal_links
from links.link_score import LinkScoreResult, score_links
from links.loops import check_redirect_loops
from links.redirects import check_redirects

__all__ = [
    "check_internal_links",
    "check_external_links",
    "check_redirects",
    "check_redirect_loops",
    "score_links",
    "LinkScoreResult",
    "run_page_checks",
    "run_site_checks",
]


def run_page_checks(page: ParsedPage, links: List[Link]) -> List[dict]:
    """
    Every check that only needs one already-fetched page's already-
    resolved link list: internal structure and external-link
    security/quality. Cheap and synchronous — safe to call once per
    page during a crawl, same as seo/accessibility/ux's page-level
    checks.
    """
    findings: List[dict] = []
    findings += check_internal_links(page, links)
    findings += check_external_links(page, links)
    return findings


async def run_site_checks(
    client: httpx.AsyncClient,
    links: List[Link],
) -> List[dict]:
    """
    Everything that needs its own live HTTP requests: redirect-chain
    characterization and redirect-loop detection over the same link
    sample. Call once per crawl (or per page, for a deeper audit) —
    not once per link, the functions themselves handle sampling and
    concurrency.
    """
    findings: List[dict] = []
    findings += await check_redirects(client, links)
    findings += await check_redirect_loops(client, links)
    return findings
