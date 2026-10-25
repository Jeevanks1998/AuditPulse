"""
Optional second check using the pa11y CLI (HTML CodeSniffer, WCAG2AA).
Needs `npm install -g pa11y`; returns [] when it isn't installed or fails.
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

# pa11y issue type -> our severity
TYPE_SEVERITY = {"error": "critical", "warning": "warning", "notice": "info"}

MAX_FINDINGS_PER_RUN = 20  # a broken template can repeat the same issue hundreds of times


def pa11y_available() -> bool:
    """True if the pa11y CLI is installed and on PATH."""
    return shutil.which(PA11Y_BINARY) is not None


async def run_pa11y(url: str, timeout: float = RUN_TIMEOUT_SECONDS) -> List[dict]:
    """Runs pa11y on `url`. Returns [] (never raises) if unavailable; [] doesn't mean "all passed"."""
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

    # pa11y exits non-zero when it finds issues; only unparseable output is a real failure.
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
    """Converts pa11y's JSON issues into findings."""
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
