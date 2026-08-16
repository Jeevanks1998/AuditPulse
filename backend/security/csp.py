"""
security/csp.py

Content-Security-Policy checks: presence (as either a response header
or a <meta http-equiv="Content-Security-Policy"> tag — the meta form
can't carry frame-ancestors/report-uri but is otherwise valid and
common on static hosting where response headers aren't configurable),
and directive-level red flags once a policy exists (wildcard sources,
'unsafe-inline'/'unsafe-eval', report-only-as-the-only-policy).

Takes an optional `page` (crawler.parser.ParsedPage) alongside the
response headers so it can be called from either security/__init__.py's
live-only path (headers, no page) or its combined path (both) without
double-reporting "missing CSP" — the meta-tag lookup only runs when a
page is actually provided.
"""

from __future__ import annotations

from typing import List, Mapping, Optional

MODULE = "security"
CATEGORY = "csp"

# Directives where a wildcard or unsafe keyword meaningfully weakens the policy.
_SCRIPT_CONTROLLING_DIRECTIVES = ("script-src", "default-src")


def check_csp(headers: Mapping[str, str], url: str, page=None) -> List[dict]:
    """
    Findings for a missing or weak Content-Security-Policy. `page` is
    optional — pass a ParsedPage to also check for a meta-tag CSP when
    no header is present; omit it to check the header only.
    """
    lower = {k.lower(): v for k, v in (headers or {}).items()}
    header_policy = lower.get("content-security-policy")
    report_only_policy = lower.get("content-security-policy-report-only")

    meta_policy = _meta_csp(page) if page is not None else None
    policy = header_policy or meta_policy

    if not policy:
        if report_only_policy:
            return [_finding(
                "warning",
                "CSP only configured in report-only mode",
                f"{url} sends `Content-Security-Policy-Report-Only` but no enforcing "
                "`Content-Security-Policy` header. Report-only mode logs violations without "
                "blocking anything, so it provides no actual protection on its own.",
                recommendation="Once the report-only policy has been validated against real "
                                "traffic, promote it to an enforcing `Content-Security-Policy` "
                                "header.",
            )]
        return [_finding(
            "warning",
            "Missing Content-Security-Policy",
            f"{url} sets no Content-Security-Policy, via header or meta tag. CSP is the "
            "primary browser-enforced defense against cross-site scripting (XSS) — without "
            "one, any injected script (via a vulnerable input, compromised dependency, or "
            "third-party widget) runs with full access to the page.",
            recommendation="Add a Content-Security-Policy starting with a conservative "
                            "baseline like `default-src 'self'; object-src 'none'; "
                            "base-uri 'self'`, then extend it directive-by-directive for "
                            "whatever third-party origins the site legitimately needs.",
        )]

    findings: List[dict] = []
    directives = _parse_directives(policy)

    for directive in _SCRIPT_CONTROLLING_DIRECTIVES:
        sources = directives.get(directive)
        if sources is None:
            continue
        if "*" in sources:
            findings.append(_finding(
                "critical",
                f"CSP {directive} allows any origin",
                f"{url}'s CSP sets `{directive} *`, which allows scripts from any origin "
                "whatsoever — functionally equivalent to not restricting script sources at "
                "all.",
                recommendation=f"Replace the wildcard in `{directive}` with an explicit list "
                                "of origins the site actually loads scripts from.",
            ))
        if "'unsafe-inline'" in sources:
            findings.append(_finding(
                "warning",
                f"CSP {directive} allows 'unsafe-inline'",
                f"{url}'s CSP `{directive}` includes 'unsafe-inline', which permits inline "
                "<script> tags and inline event handlers to run — the exact vector CSP is "
                "usually adopted to close off, since it means injected inline script isn't "
                "blocked either.",
                recommendation="Move inline scripts to external files (or adopt a nonce/hash "
                                "-based CSP) and drop 'unsafe-inline'.",
            ))
        if "'unsafe-eval'" in sources:
            findings.append(_finding(
                "warning",
                f"CSP {directive} allows 'unsafe-eval'",
                f"{url}'s CSP `{directive}` includes 'unsafe-eval', permitting `eval()`, "
                "`new Function()`, and similar string-to-code execution — a common gadget "
                "for turning a data-injection bug into script execution.",
                recommendation="Remove 'unsafe-eval' and refactor any code relying on it "
                                "(often a bundler/legacy-library default rather than "
                                "intentional app code).",
            ))
        break  # default-src only matters here if script-src doesn't override it

    if "object-src" not in directives and "default-src" not in directives:
        findings.append(_finding(
            "info",
            "CSP has no object-src restriction",
            f"{url}'s CSP doesn't set `object-src` (or a `default-src` fallback), leaving "
            "<object>/<embed>/<applet> plugin content unrestricted — a legacy but still-live "
            "route for executing content outside the script-src rules.",
            recommendation="Add `object-src 'none'` unless the site genuinely embeds plugin "
                            "content.",
        ))

    if "base-uri" not in directives:
        findings.append(_finding(
            "info",
            "CSP has no base-uri restriction",
            f"{url}'s CSP doesn't restrict `base-uri`, so an injected `<base>` tag could "
            "rewrite the base URL every relative script/link/form on the page resolves "
            "against.",
            recommendation="Add `base-uri 'self'` to prevent base-tag injection from "
                            "redirecting relative URLs off-site.",
        ))

    return findings


def _meta_csp(page) -> Optional[str]:
    for tag in page.soup.find_all("meta"):
        if (tag.get("http-equiv") or "").strip().lower() == "content-security-policy":
            content = (tag.get("content") or "").strip()
            if content:
                return content
    return None


def _parse_directives(policy: str) -> dict:
    """{'script-src': {'self', 'https://example.com'}, ...} — lowercased directive names."""
    directives: dict = {}
    for chunk in policy.split(";"):
        parts = chunk.strip().split()
        if not parts:
            continue
        name, sources = parts[0].lower(), {s.lower() for s in parts[1:]}
        directives[name] = sources
    return directives


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
