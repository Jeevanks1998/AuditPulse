"""
security/hsts.py

Strict-Transport-Security (HSTS) checks: presence, a max-age long
enough to actually protect repeat visitors, and the includeSubDomains /
preload directives. HSTS only makes sense on HTTPS — security/https.py
owns the "site isn't even served over HTTPS" finding, so this module
no-ops cleanly when called for a plain-http URL rather than piling on
a redundant finding.
"""

from __future__ import annotations

import re
from typing import List, Mapping, Optional
from urllib.parse import urlparse

MODULE = "security"
CATEGORY = "hsts"

# Six months, the widely-cited practical minimum for HSTS to be meaningful.
MIN_RECOMMENDED_MAX_AGE = 15_768_000
# One year, required for HSTS preload-list submission.
PRELOAD_MIN_MAX_AGE = 31_536_000

_MAX_AGE_RE = re.compile(r"max-age\s*=\s*(\d+)", re.IGNORECASE)


def check_hsts(headers: Mapping[str, str], url: str) -> List[dict]:
    """Findings for a missing or weak Strict-Transport-Security header."""
    if urlparse(url).scheme != "https":
        return []

    lower = {k.lower(): v for k, v in (headers or {}).items()}
    raw = lower.get("strict-transport-security")

    if not raw:
        return [_finding(
            "warning",
            "Missing HSTS header",
            f"{url} is served over HTTPS but sends no `Strict-Transport-Security` header. "
            "Without it, a browser that hasn't already been told to force HTTPS for this "
            "domain can still be tricked (e.g. on public wifi) into an insecure HTTP request "
            "before any redirect has a chance to run.",
            recommendation="Add `Strict-Transport-Security: max-age=31536000; "
                            "includeSubDomains` once every subdomain is confirmed to serve "
                            "HTTPS correctly.",
        )]

    match = _MAX_AGE_RE.search(raw)
    max_age = int(match.group(1)) if match else 0
    include_subdomains = "includesubdomains" in raw.lower()
    preload = "preload" in raw.lower()

    findings: List[dict] = []

    if max_age == 0:
        findings.append(_finding(
            "critical",
            "HSTS max-age is zero",
            f"{url} sends `Strict-Transport-Security` with max-age=0, which actively tells "
            "browsers to *stop* enforcing HTTPS for this domain — the opposite of HSTS's "
            "purpose. This value is normally only intentional when deliberately disabling "
            "HSTS during a migration.",
            recommendation="Set max-age to a real duration (31536000 for one year) unless "
                            "disabling HSTS is genuinely intentional right now.",
        ))
    elif max_age < MIN_RECOMMENDED_MAX_AGE:
        findings.append(_finding(
            "warning",
            "HSTS max-age too short",
            f"{url}'s HSTS max-age is {max_age} seconds (~{max_age // 86400} days) — below "
            "the ~6 month duration generally recommended for HSTS to reliably protect "
            "returning visitors between site checks.",
            recommendation="Increase max-age to at least 15768000 (6 months); 31536000 "
                            "(1 year) is standard once HTTPS is confirmed stable.",
        ))

    if not include_subdomains:
        findings.append(_finding(
            "info",
            "HSTS missing includeSubDomains",
            f"{url}'s HSTS header doesn't set `includeSubDomains`, so subdomains aren't "
            "covered and remain vulnerable to the same downgrade issue HSTS otherwise "
            "prevents on the main domain.",
            recommendation="Add `includeSubDomains` once every subdomain actually serves "
                            "valid HTTPS — otherwise this would break any subdomain still on "
                            "plain HTTP.",
        ))

    if preload and max_age < PRELOAD_MIN_MAX_AGE:
        findings.append(_finding(
            "info",
            "HSTS preload flag set without qualifying max-age",
            f"{url}'s HSTS header includes `preload` but max-age is only {max_age} seconds — "
            f"below the {PRELOAD_MIN_MAX_AGE} (1 year) the HSTS preload list requires. The "
            "preload flag alone doesn't submit the domain anywhere, but it won't qualify "
            "until max-age meets that bar.",
            recommendation=f"Raise max-age to at least {PRELOAD_MIN_MAX_AGE} if submission to "
                            "the browser preload list is intended.",
        ))

    return findings


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
