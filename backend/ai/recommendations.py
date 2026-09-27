"""
ai/recommendations.py

Generates the "ai" module's findings for a completed audit — the same
Issue-shaped {module, severity, title, description, recommendation} dicts
every other module (security/, mobile/, forms/, ...) produces, so this
flows through models.issue.sync_issues_from_findings and reports/ without
any special-casing. This is what used to live inline in
services.ai_service._findings_from_anthropic / _heuristic_findings before
the ai/ package existed; services.ai_service now just calls through to
`generate_recommendations` below.

No network call is made unless ai.provider.is_configured() — a failed or
unconfigured call always falls back to `_heuristic_recommendations` rather
than raising, so a missing credential (or an outage) can never take the
whole audit pipeline down with it.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from config.logging import logger
from ai.provider import AIProviderError, call_ai_json

MODULE = "ai"
MAX_RECOMMENDATIONS = 3

_VALID_SEVERITIES = {"critical", "warning", "info"}


async def generate_recommendations(
    url: str,
    breakdown: Dict[str, int],
    findings: Optional[List[dict]] = None,
) -> List[dict]:
    """
    Returns up to MAX_RECOMMENDATIONS Issue-shaped finding dicts (module="ai")
    describing what an AI reviewer would flag about the audited page, given
    the other modules' scores and (optionally) their raw findings for extra
    context.
    """
    try:
        return await _recommendations_from_ai(url, breakdown, findings or [])
    except AIProviderError as exc:
        logger.warning(f"ai.recommendations: falling back to heuristic recommendations: {exc}")
        return _heuristic_recommendations(url, breakdown)


# --------------------------------------------------------------------------
# AI-backed path
# --------------------------------------------------------------------------
async def _recommendations_from_ai(url: str, breakdown: Dict[str, int], findings: List[dict]) -> List[dict]:
    weak_titles = [f.get("title") for f in findings if f.get("severity") in ("critical", "warning")][:8]
    context = f"module scores out of 100: {breakdown}"
    if weak_titles:
        context += f"; already-flagged issues: {weak_titles}"

    prompt = (
        "You are an automated website-audit assistant. Given these results for "
        f"{url} ({context}), list up to {MAX_RECOMMENDATIONS} concrete, non-redundant "
        "issues a site owner should fix next. Respond with ONLY a JSON array (no prose, "
        'no markdown fences) of objects with keys "severity" (one of "critical", '
        '"warning", "info"), "title", "description", and "recommendation" (a specific, '
        "actionable next step)."
    )
    items = await call_ai_json(prompt, max_tokens=600)
    if not isinstance(items, list):
        raise AIProviderError("Expected a JSON array of recommendations")

    recommendations: List[dict] = []
    for item in items[:MAX_RECOMMENDATIONS]:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        recommendations.append(_finding(item))

    if not recommendations:
        raise AIProviderError("AI response yielded no usable recommendations")
    return recommendations


def _finding(item: dict) -> dict:
    severity = item.get("severity", "info")
    if severity not in _VALID_SEVERITIES:
        severity = "info"
    return {
        "module": MODULE,
        "severity": severity,
        "title": item.get("title", "AI review finding"),
        "description": item.get("description", ""),
        "recommendation": item.get("recommendation"),
    }


# --------------------------------------------------------------------------
# Heuristic fallback — no provider configured, or the call failed
# --------------------------------------------------------------------------
def _heuristic_recommendations(url: str, breakdown: Dict[str, int]) -> List[dict]:
    """Deterministic fallback so the "ai" module always yields something in local/dev."""
    if not breakdown:
        return []

    weakest_module = min(breakdown, key=breakdown.get)
    score = breakdown[weakest_module]
    severity = "critical" if score < 60 else "warning" if score < 80 else "info"

    return [
        {
            "module": MODULE,
            "severity": severity,
            "title": f"AI review: {weakest_module.title()} is the biggest opportunity",
            "description": (
                f"Based on the other module scores, {weakest_module} ({score}/100) is where "
                f"{url} would benefit most from attention first."
            ),
            "recommendation": f"Prioritize the {weakest_module} findings from this audit before the next run.",
        }
    ]
