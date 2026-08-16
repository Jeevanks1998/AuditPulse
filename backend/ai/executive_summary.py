"""
ai/executive_summary.py

Generates the short, plain-English paragraph that sits at the top of a
report (reports/generator.py -> ReportPayload.executive_summary,
report.html's summary banner) — a couple of sentences a non-technical
stakeholder can read to understand where the site stands and what
matters most, without scrolling through every finding.

Same fallback contract as the rest of ai/: a missing/unconfigured
provider or a failed call never raises out of `generate_executive_summary`,
it just returns a deterministic, template-built summary instead.
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
    try:
        return await _summary_from_ai(url, overall, breakdown, findings or [])
    except AIProviderError as exc:
        logger.warning(f"ai.executive_summary: falling back to heuristic summary: {exc}")
        return _heuristic_summary(url, overall, breakdown, findings or [])


# --------------------------------------------------------------------------
# AI-backed path
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Heuristic fallback
# --------------------------------------------------------------------------
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
