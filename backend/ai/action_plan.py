"""
Turns prioritized findings into a plan: quick wins, short term, long term.

Grouping comes from priority.py (no AI), so it always matches the ranked
list. AI only rewords the steps; plain wording is the fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config.logging import logger
from ai.priority import PrioritizedFinding, prioritize_findings
from ai.provider import AIProviderError, call_ai_json

MAX_STEPS_PER_HORIZON = 5

# Which horizon each severity goes into by default.
_HORIZON_BY_SEVERITY = {
    "critical": "quick_wins",
    "warning": "short_term",
    "info": "long_term",
}


@dataclass
class ActionPlan:
    quick_wins: List[dict] = field(default_factory=list)
    short_term: List[dict] = field(default_factory=list)
    long_term: List[dict] = field(default_factory=list)


async def generate_action_plan(
    url: str,
    breakdown: Dict[str, int],
    findings: Optional[List[dict]] = None,
) -> ActionPlan:
    """Builds a horizon-grouped action plan from an audit's findings."""
    findings = findings or []
    prioritized = prioritize_findings(findings, breakdown)
    if not prioritized:
        return ActionPlan()

    try:
        step_text_by_title = await _step_wording_from_ai(url, prioritized)
    except AIProviderError as exc:
        logger.warning(f"ai.action_plan: falling back to heuristic step wording: {exc}")
        step_text_by_title = {}

    plan = ActionPlan()
    for item in prioritized:
        horizon = _HORIZON_BY_SEVERITY.get(item.severity, "short_term")
        bucket = getattr(plan, horizon)
        if len(bucket) >= MAX_STEPS_PER_HORIZON:
            continue
        step = step_text_by_title.get(item.title) or _heuristic_step_text(item)
        bucket.append(
            {
                "title": item.title,
                "module": item.module,
                "severity": item.severity,
                "effort": item.effort,
                "step": step,
            }
        )
    return plan


# AI wording
async def _step_wording_from_ai(url: str, prioritized: List[PrioritizedFinding]) -> Dict[str, str]:
    top = prioritized[: MAX_STEPS_PER_HORIZON * 3]
    items = [{"title": p.title, "description": p.description, "severity": p.severity} for p in top]

    prompt = (
        f"You are writing a step-by-step remediation plan for a website audit of {url}. For each item "
        f"below, write ONE short, concrete, actionable sentence describing the fix. Items: {items}. "
        'Respond with ONLY a JSON object (no prose, no markdown fences) mapping each item\'s exact '
        '"title" to its one-sentence action step.'
    )
    result = await call_ai_json(prompt, max_tokens=800)
    if not isinstance(result, dict):
        raise AIProviderError("Expected a JSON object mapping titles to step text")
    return {str(k): str(v) for k, v in result.items() if v}


# Fallback wording
def _heuristic_step_text(item: PrioritizedFinding) -> str:
    if item.recommendation:
        return item.recommendation
    return f"Fix: {item.title}" if item.title else "Review this finding and address the root cause."
