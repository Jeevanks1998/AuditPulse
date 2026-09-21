"""
security/

A dedicated, granular security-check package — one file per concern —
that supersedes the `breakdown["security"] = random.randint(80, 99)`
placeholder in services.audit_service.run_audit_pipeline. Every check
function returns findings in the same {module, category, severity,
title, description, recommendation} shape services.audit_service /
models.issue already persist, so nothing downstream (Issue sync,
report.html, history) needs to change to consume them — same contract
as seo/, accessibility/, and performance/.

Unlike accessibility/'s page-level-vs-live-render split, almost
everything here needs live network access — there's no meaningful
"security" signal sitting statically in already-parsed HTML except
mixed content. The one live GET (security/https.py) is deliberately
the shared entry point: it's the only module that both produces its
own findings *and* hands back data (response headers, resolved final
URL) that headers.py/hsts.py/csp.py all key off, so this package makes
exactly one HTTP request plus one TLS handshake per audited URL rather
than each check re-fetching independently.

    https          — HTTPS enforcement: scheme, HTTPS->HTTP downgrades,
                      and whether the http:// origin redirects to https
    ssl            — certificate trust/expiry/protocol via a raw TLS
                      handshake (security/ssl.py; stdlib `ssl`, no
                      extra dependency)
    headers        — X-Content-Type-Options, clickjacking protection,
                      Referrer-Policy, Permissions-Policy, COOP, and
                      server/version information disclosure
    hsts           — Strict-Transport-Security presence/max-age/
                      includeSubDomains/preload
    csp            — Content-Security-Policy presence (header or meta
                      tag) and directive-level weaknesses
    mixed_content  — page-level: http:// resources loaded from an
                      https:// page (crawler.parser.ParsedPage, no
                      network call of its own)
    security_score — turns any list of these findings into a weighted
                      0-100 score with a per-category breakdown, same
                      shape as Audit.breakdown["security"] already uses

Usage — wiring this into the real pipeline (crawler.crawler.Crawler
already produces a ParsedPage per page; this replaces the security
portion of extract_signals' findings, it doesn't replace the whole
crawl):

    from security import run_security_checks

    result = await run_security_checks(client, homepage)
    breakdown["security"] = result.score.overall
    findings += result.findings
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
    """
    The one check in this package that only needs an already-fetched,
    already-parsed page. Cheap and synchronous — safe to call once per
    page during a crawl, same as accessibility/seo's page-level checks.
    """
    return check_mixed_content(page)


async def run_live_checks(
    client: httpx.AsyncClient, url: str, page: Optional[ParsedPage] = None
) -> tuple[List[dict], SecurityScoreResult]:
    """
    Everything that needs its own live request: one GET (security/
    https.py, which also probes the http:// origin) plus one TLS
    handshake (security/ssl.py), with headers.py/hsts.py/csp.py run
    against whatever response headers that GET returned. Call this once
    per URL — typically the homepage — not once per crawled page.

    Pass `page` when it's available so csp.py can also check for a
    meta-tag CSP; omit it to check the header only. Returns
    (findings, score) — score is computed here (rather than left to the
    caller) since it needs to know whether ssl.py actually ran a
    handshake (score_security's ssl_checked flag) to score the ssl
    category correctly on a plain-http URL.
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
    """Lightweight container mirroring accessibility.AccessibilityAuditResult's shape."""

    findings: List[dict]
    score: SecurityScoreResult
    ssl_info: SslInfo


async def run_security_checks(client: httpx.AsyncClient, page: ParsedPage) -> SecurityAuditResult:
    """
    Convenience one-call entry point for a single page: runs the page-
    level mixed-content check plus every live check for page.url, then
    scores the combined findings. Prefer run_page_checks/run_live_checks
    separately when a caller wants page-level checks run across every
    crawled page but the (much costlier) live checks run only once for
    the site's homepage — the common real-world shape, since HTTPS/TLS/
    header configuration is normally identical across a whole site.
    """
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
