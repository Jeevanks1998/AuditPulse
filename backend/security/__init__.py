"""
Security checks (not used by the audit pipeline yet). One GET and one TLS
handshake per URL are shared by all checks:
  https          - HTTPS and http -> https redirects
  ssl            - certificate validity and expiry
  headers        - security headers and server version leaks
  hsts           - Strict-Transport-Security
  csp            - Content-Security-Policy
  mixed_content  - http resources on an https page
  security_score - 0-100 score
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import httpx

from crawler.parser import ParsedPage

from security.csp import check_csp
from security.headers import check_security_headers
from security.hsts import check_hsts
from security.https import check_https
from security.mixed_content import check_mixed_content
from security.security_score import SecurityScoreResult, score_security
from security.ssl import SslInfo, check_ssl

__all__ = [
    "check_https",
    "check_ssl",
    "SslInfo",
    "check_security_headers",
    "check_hsts",
    "check_csp",
    "check_mixed_content",
    "score_security",
    "SecurityScoreResult",
    "run_page_checks",
    "run_live_checks",
    "run_security_checks",
    "SecurityAuditResult",
]


def run_page_checks(page: ParsedPage) -> List[dict]:
    """The only check that needs just the parsed page (mixed content)."""
    return check_mixed_content(page)


async def run_live_checks(
    client: httpx.AsyncClient, url: str, page: Optional[ParsedPage] = None
) -> tuple[List[dict], SecurityScoreResult]:
    """Live checks for one URL (usually the homepage): one GET, one TLS handshake,
    and header checks on that response. Pass `page` to also check a meta-tag CSP.
    Returns (findings, score).
    """
    https_findings, headers, final_url = await check_https(client, url)
    ssl_findings, ssl_info = await check_ssl(final_url)

    findings: List[dict] = []
    findings += https_findings
    findings += ssl_findings
    findings += check_security_headers(headers or {}, final_url)
    findings += check_hsts(headers or {}, final_url)
    findings += check_csp(headers or {}, final_url, page=page)

    score = score_security(findings, ssl_checked=ssl_info.checked)
    return findings, score


@dataclass
class SecurityAuditResult:
    """Result container: findings and score."""

    findings: List[dict]
    score: SecurityScoreResult
    ssl_info: SslInfo


async def run_security_checks(client: httpx.AsyncClient, page: ParsedPage) -> SecurityAuditResult:
    """Runs all security checks for one page and scores them."""
    url = page.url
    https_findings, headers, final_url = await check_https(client, url)
    ssl_findings, ssl_info = await check_ssl(final_url)

    findings: List[dict] = []
    findings += run_page_checks(page)
    findings += https_findings
    findings += ssl_findings
    findings += check_security_headers(headers or {}, final_url)
    findings += check_hsts(headers or {}, final_url)
    findings += check_csp(headers or {}, final_url, page=page)

    score = score_security(findings, ssl_checked=ssl_info.checked)

    return SecurityAuditResult(findings=findings, score=score, ssl_info=ssl_info)
