"""
AI findings for the "ai" module, in the same shape as every other module's findings.

Falls back to fixed recommendations when the AI is unavailable, so a missing
key or an outage never fails an audit.
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
    """Returns up to MAX_RECOMMENDATIONS findings (module="ai") based on the other modules' scores and findings."""
    try:
        return await _recommendations_from_ai(url, breakdown, findings or [])
    except AIProviderError as exc:
        logger.warning(f"ai.recommendations: falling back to heuristic recommendations: {exc}")
        return _heuristic_recommendations(url, breakdown)


# AI path
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


# Fallback
def _heuristic_recommendations(url: str, breakdown: Dict[str, int]) -> List[dict]:
    """Fallback so the "ai" module always returns something."""
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
