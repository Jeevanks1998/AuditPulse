"""
Writes the short summary paragraph at the top of the report.

If the AI is unavailable, a template summary is used instead.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from config.logging import logger
from ai.provider import AIProviderError, call_ai

MAX_SUMMARY_SENTENCES_HINT = 4


async def generate_executive_summary(
    url: str,
    overall: int,
    breakdown: Dict[str, int],
    findings: Optional[List[dict]] = None,
) -> str:
    """Returns a short natural-language executive summary for the audit."""
    if not breakdown:
        return _unscored_summary(url, findings or [])
    try:
        return await _summary_from_ai(url, overall, breakdown, findings or [])
    except AIProviderError as exc:
        logger.warning(f"ai.executive_summary: falling back to heuristic summary: {exc}")
        return _heuristic_summary(url, overall, breakdown, findings or [])


# AI path
async def _summary_from_ai(url: str, overall: int, breakdown: Dict[str, int], findings: List[dict]) -> str:
    critical_titles = [f.get("title") for f in findings if f.get("severity") == "critical"][:5]

    prompt = (
        "You are writing the executive summary of a website audit report for a "
        f"non-technical stakeholder. Site: {url}. Overall score: {overall}/100. "
        f"Per-module scores: {breakdown}. Critical issues found: {critical_titles or 'none'}. "
        f"Write at most {MAX_SUMMARY_SENTENCES_HINT} sentences, plain prose, no markdown, "
        "no headings, no bullet points — just the paragraph itself."
    )
    text = await call_ai(prompt, max_tokens=300)
    return text.strip()


def _unscored_summary(url: str, findings: List[dict]) -> str:
    """Used when no module produced a score."""
    blocked = next((f for f in findings if f.get("module") == "site_access"), None)
    if blocked:
        return (f"{url} could not be audited: the website's bot protection blocked AuditPulse's browser, "
                "so consent, analytics and journeys were not checked and nothing is scored. "
                "Ask the site owner to allowlist AuditPulse, then run the audit again.")
    sentence = (f"{url} could not be scored in this run: no audited module produced a score "
                "(for a Journey Map audit this means no interaction could be tested — see the "
                "Journey Map section for the reason).")
    real = [f for f in findings if f.get("severity") in ("critical", "warning")]
    if real:
        sentence += f" {len(real)} issue{'s' if len(real) != 1 else ''} were still found and are listed below."
    return sentence


# Fallback
def _heuristic_summary(url: str, overall: int, breakdown: Dict[str, int], findings: List[dict]) -> str:
    band = "strong" if overall >= 80 else "mixed" if overall >= 50 else "weak"
    critical_count = sum(1 for f in findings if f.get("severity") == "critical")

    sentence = f"{url} scored {overall}/100 overall, a {band} result across the modules audited."
    if breakdown:
        weakest = min(breakdown, key=breakdown.get)
        sentence += f" {weakest.title()} ({breakdown[weakest]}/100) is the area most in need of attention."
    if critical_count:
        plural = "issue" if critical_count == 1 else "issues"
        sentence += f" This audit flagged {critical_count} critical {plural} that should be addressed first."
    else:
        sentence += " No critical issues were flagged in this run."
    return sentence
