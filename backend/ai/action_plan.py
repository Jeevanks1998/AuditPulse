"""
ai/action_plan.py

Turns a completed audit's prioritized findings (ai/priority.py) into a
concrete "what to do, in what order" plan grouped into three horizons —
quick_wins, short_term, long_term — for reports/generator.py's
`action_plan` field. This is the last step of the AI report pipeline:
executive_summary.py says where things stand, business_impact.py says why
it matters, this says what to actually do about it.

Grouping is derived from ai/priority.py's deterministic effort estimate
(never re-run through the AI provider), so the buckets a stakeholder sees
always agree with the ranked list above them; only the step *wording* is
optionally enriched by the AI provider, with a plain heuristic phrasing
as the fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config.logging import logger
from ai.priority import PrioritizedFinding, prioritize_findings
from ai.provider import AIProviderError, call_ai_json

MAX_STEPS_PER_HORIZON = 5

# Which severities land in which horizon. Critical items are quick wins
# (fix now, they're cheap to justify) or short-term depending on effort;
# info-level items are long-term/nice-to-have by default.
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


# --------------------------------------------------------------------------
# AI-backed step wording
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Heuristic fallback
# --------------------------------------------------------------------------
def _heuristic_step_text(item: PrioritizedFinding) -> str:
    if item.recommendation:
        return item.recommendation
    return f"Fix: {item.title}" if item.title else "Review this finding and address the root cause."
