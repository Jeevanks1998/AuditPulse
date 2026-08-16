"""
security/https.py

The entry point for the rest of security/'s live checks: does one GET
against the audited URL and, when it lands on https, a second GET
against the plain-http equivalent to confirm the server actually
redirects there rather than merely happening to be reachable over TLS
if asked nicely. Every other live check in this package (headers.py,
hsts.py, csp.py, ssl.py) either reuses the response headers this
returns or takes the resolved final URL as its own starting point, so
this module runs first — see security/__init__.py::run_live_checks.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlparse, urlunparse

import httpx

from config.logging import logger

MODULE = "security"
CATEGORY = "https"

REQUEST_TIMEOUT_SECONDS = 15.0


async def check_https(
    client: httpx.AsyncClient, url: str
) -> tuple[List[dict], Optional[httpx.Headers], str]:
    """
    Returns (findings, response_headers, final_url). `response_headers`
    is None only when the request failed outright (network error, not
    an HTTP error status) — callers should treat that as "no header
    data available" rather than assuming headers are simply empty.
    `final_url` is the resolved URL after any redirects, for downstream
    checks (ssl.py, hsts.py) to key off instead of the original input.
    """
    parsed = urlparse(url)
    findings: List[dict] = []

    if parsed.scheme != "https":
        findings.append(_finding(
            "critical",
            "Site not served over HTTPS",
            f"{url} is served over plain HTTP. All traffic — including any form submissions, "
            "login credentials, or session cookies — travels unencrypted and can be read or "
            "altered by anyone on the network path.",
            recommendation="Obtain a TLS certificate (Let's Encrypt is free) and serve the "
                            "site over HTTPS, then redirect all HTTP requests to HTTPS.",
        ))

    try:
        response = await client.get(url, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError as exc:
        logger.warning(f"security.https: request failed for {url}: {exc}")
        findings.append(_finding(
            "warning",
            "Could not verify HTTPS behavior",
            f"A request to {url} failed before headers could be checked: {exc}.",
            recommendation="Confirm the site is reachable; re-run the audit once it is.",
        ))
        return findings, None, url

    final_url = str(response.url)
    final_parsed = urlparse(final_url)

    if parsed.scheme == "https" and final_parsed.scheme != "https":
        findings.append(_finding(
            "critical",
            "HTTPS request downgraded to HTTP",
            f"Requesting {url} over HTTPS ended up at {final_url} over plain HTTP after "
            "following redirects, exposing everything downstream of that hop.",
            recommendation="Remove any redirect that sends HTTPS traffic to an HTTP URL; "
                            "every internal redirect should stay on HTTPS.",
        ))

    if parsed.scheme == "https":
        http_findings = await _check_http_redirects_to_https(client, url)
        findings += http_findings

    return findings, response.headers, final_url


async def _check_http_redirects_to_https(client: httpx.AsyncClient, https_url: str) -> List[dict]:
    """Requests the plain-http equivalent of an https URL and checks it redirects to https."""
    parsed = urlparse(https_url)
    http_url = urlunparse(parsed._replace(scheme="http"))

    try:
        response = await client.get(
            http_url, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True
        )
    except httpx.HTTPError as exc:
        # Plenty of properly-configured sites simply don't listen on :80 at all —
        # that's not a finding, just means this particular check has nothing to say.
        logger.debug(f"security.https: HTTP-origin check skipped for {http_url}: {exc}")
        return []

    final_scheme = urlparse(str(response.url)).scheme
    if final_scheme != "https":
        return [_finding(
            "critical",
            "HTTP version does not redirect to HTTPS",
            f"{http_url} responds without redirecting to HTTPS (ended at {response.url}, "
            f"HTTP {response.status_code}). Visitors who type the domain without \"https://\", "
            "or follow an old http:// link, get served the insecure version instead of being "
            "sent to the secure one.",
            recommendation="Add a server-level redirect (301) from every HTTP request to the "
                            "equivalent HTTPS URL.",
        )]

    if not response.history:
        return [_finding(
            "info",
            "HTTP origin reachable without an explicit redirect",
            f"{http_url} returned HTTP {response.status_code} directly on the http:// origin "
            "rather than issuing a redirect, even though the content appears to match the "
            "HTTPS version. This can happen behind some proxies/CDNs; worth confirming an "
            "explicit redirect exists at the origin server too.",
            recommendation="Configure an explicit 301 redirect from HTTP to HTTPS at the "
                            "server or load balancer, rather than relying on upstream behavior.",
        )]

    return []


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
