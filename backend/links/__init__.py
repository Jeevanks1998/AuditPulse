"""
Link checks (not used by the audit pipeline yet):
  internal   - dead ends, nofollow on own links, "click here" text
  external   - target=_blank without noopener, http links, too many outbound links
  redirects  - long chains, temporary redirects, http that never upgrades
  loops      - real redirect loops
  link_score - 0-100 score
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
    """Checks that only need the page and its links."""
    findings: List[dict] = []
    findings += check_internal_links(page, links)
    findings += check_external_links(page, links)
    return findings


async def run_site_checks(
    client: httpx.AsyncClient,
    links: List[Link],
) -> List[dict]:
    """Checks that make live requests (redirects and loops) on a sample of links."""
    findings: List[dict] = []
    findings += await check_redirects(client, links)
    findings += await check_redirect_loops(client, links)
    return findings
