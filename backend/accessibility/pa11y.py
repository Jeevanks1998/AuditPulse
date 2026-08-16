"""
accessibility/pa11y.py

Optional second opinion from pa11y (https://github.com/pa11y/pa11y), a
Node CLI that runs the HTML CodeSniffer WCAG2AA ruleset against a
rendered page via headless Chrome. It overlaps with accessibility/axe.py
(also Chrome-rendered, via PSI/Lighthouse) but uses a different rule
engine, so the two occasionally disagree — worth surfacing both rather
than picking one, the same philosophy performance/pagespeed.py uses for
lab vs field data.

pa11y + Node + a Chrome binary is a heavy, optional dependency (not in
requirements.txt, mirrors the Playwright note in crawler/screenshots.py
— `npm install -g pa11y` is a one-time host setup, not a pip package).
Every entry point here degrades to returning [] rather than raising
when the `pa11y` binary isn't on PATH, times out, or errors, so a
missing local install can never take down the rest of the audit
pipeline.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import List, Optional

from config.logging import logger

MODULE = "accessibility"
CATEGORY = "pa11y"

PA11Y_BINARY = "pa11y"
RUN_TIMEOUT_SECONDS = 45.0

# pa11y issue.type -> our severity. "error" is a definite WCAG2AA failure;
# "warning"/"notice" are lower-confidence or advisory.
TYPE_SEVERITY = {"error": "critical", "warning": "warning", "notice": "info"}

MAX_FINDINGS_PER_RUN = 20  # a broken template can otherwise repeat the same issue hundreds of times


def pa11y_available() -> bool:
    """True if the pa11y CLI is installed and on PATH."""
    return shutil.which(PA11Y_BINARY) is not None


async def run_pa11y(url: str, timeout: float = RUN_TIMEOUT_SECONDS) -> List[dict]:
    """
    Runs `pa11y --reporter json <url>` and returns findings parsed from
    its issue list. Returns [] (never raises) if pa11y isn't installed,
    the run times out, or its output isn't parseable JSON — callers
    should treat that as "unavailable", not "everything passed".
    """
    if not pa11y_available():
        logger.info("accessibility.pa11y: pa11y CLI not found on PATH — skipping (optional, see module docstring)")
        return []

    try:
        process = await asyncio.create_subprocess_exec(
            PA11Y_BINARY, "--reporter", "json", "--timeout", str(int(timeout * 1000)), url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout + 5)
        except asyncio.TimeoutError:
            process.kill()
            logger.warning(f"accessibility.pa11y: run timed out for {url}")
            return []
    except FileNotFoundError:
        logger.info("accessibility.pa11y: pa11y CLI disappeared from PATH between check and exec — skipping")
        return []
    except OSError as exc:
        logger.warning(f"accessibility.pa11y: failed to launch pa11y for {url}: {exc}")
        return []

    # pa11y exits non-zero when it finds errors — that's expected, not a failure.
    # A genuinely broken run (crash, bad URL, no Chrome) produces no parseable JSON at all.
    try:
        issues = json.loads(stdout.decode("utf-8", errors="ignore") or "[]")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning(
            f"accessibility.pa11y: non-JSON output for {url}: {exc}; stderr: "
            f"{stderr.decode('utf-8', errors='ignore')[:300]}"
        )
        return []

    return check_pa11y_issues(issues)


def check_pa11y_issues(issues: Optional[List[dict]]) -> List[dict]:
    """Turns pa11y's raw JSON issue list into our finding shape."""
    if not issues:
        return []

    findings: List[dict] = []
    for issue in issues[:MAX_FINDINGS_PER_RUN]:
        findings.append(_finding_from_issue(issue))

    remaining = len(issues) - MAX_FINDINGS_PER_RUN
    if remaining > 0:
        findings.append(_finding(
            "info",
            "Additional pa11y issues not shown",
            f"pa11y reported {remaining} more issue(s) beyond the {MAX_FINDINGS_PER_RUN} shown, "
            "often repeats of the same underlying template problem.",
            recommendation="Fix the issues above first; re-run pa11y afterward since fixing "
                            "one templated problem often clears many of the remaining ones too.",
        ))

    return findings


def _finding_from_issue(issue: dict) -> dict:
    severity = TYPE_SEVERITY.get((issue.get("type") or "").lower(), "info")
    code = issue.get("code") or "unknown-rule"
    message = issue.get("message") or "pa11y flagged an accessibility issue."
    selector = issue.get("selector")
    context = issue.get("context")

    description = message
    if selector:
        description += f" Element: {selector}."
    if context and len(context) < 200:
        description += f" Markup: {context.strip()}"

    return _finding(
        severity,
        f"pa11y: {code}",
        description,
        recommendation="See the WCAG success criterion referenced in the pa11y rule code "
                        f"({code}) for the specific fix required.",
    )


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
