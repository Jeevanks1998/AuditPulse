"""
Turns technical findings into business impact (trust, conversions, legal risk).

Shown next to the findings, not instead of them. If the AI is unavailable,
a fixed template per module is used, so this never fails an audit.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from config.logging import logger
from ai.provider import AIProviderError, call_ai_json

MAX_IMPACT_ITEMS = 5

# Fallback wording per module.
_MODULE_IMPACT_TEMPLATES: Dict[str, str] = {
    "consent": "Non-compliant consent handling carries regulatory (GDPR/CCPA) risk and fines.",
    "analytics": "Gaps in tracking mean decisions get made on incomplete or wrong data.",
    "ai": "Signals a broader gap the automated review considered high-priority.",
}
_DEFAULT_IMPACT = "Left unresolved, this continues to work against the site's core goals."


async def generate_business_impact(
    url: str,
    breakdown: Dict[str, int],
    findings: Optional[List[dict]] = None,
) -> List[dict]:
    """Returns up to MAX_IMPACT_ITEMS {title, impact, affected_area, severity} items for business readers."""
    findings = findings or []
    try:
        return await _impact_from_ai(url, breakdown, findings)
    except AIProviderError as exc:
        logger.warning(f"ai.business_impact: falling back to heuristic impact statements: {exc}")
        return _heuristic_impact(findings)


# AI path
async def _impact_from_ai(url: str, breakdown: Dict[str, int], findings: List[dict]) -> List[dict]:
    notable = [f for f in findings if f.get("severity") in ("critical", "warning")][:10]
    if not notable:
        return []

    finding_summaries = [
        {"module": f.get("module"), "severity": f.get("severity"), "title": f.get("title")} for f in notable
    ]
    prompt = (
        f"You are translating a technical website audit of {url} into business impact for a "
        f"non-technical stakeholder. Findings: {finding_summaries}. For up to {MAX_IMPACT_ITEMS} of the "
        "most important findings, respond with ONLY a JSON array (no prose, no markdown fences) of "
        'objects with keys "title" (the original finding title), "affected_area" (e.g. "Conversions", '
        '"SEO traffic", "Legal/Compliance", "Brand trust"), "impact" (1-2 plain-English sentences on the '
        'business cost of leaving it unfixed), and "severity" (carried over from the finding).'
    )
    items = await call_ai_json(prompt, max_tokens=700)
    if not isinstance(items, list):
        raise AIProviderError("Expected a JSON array of business-impact items")

    impacts = [_impact_item(item) for item in items[:MAX_IMPACT_ITEMS] if isinstance(item, dict) and item.get("title")]
    if not impacts:
        raise AIProviderError("AI response yielded no usable business-impact items")
    return impacts


def _impact_item(item: dict) -> dict:
    return {
        "title": item.get("title", ""),
        "affected_area": item.get("affected_area", "General"),
        "impact": item.get("impact", ""),
        "severity": item.get("severity", "info"),
    }


# Fallback
def _heuristic_impact(findings: List[dict]) -> List[dict]:
    notable = [f for f in findings if f.get("severity") in ("critical", "warning")][:MAX_IMPACT_ITEMS]
    impacts = []
    for f in notable:
        module = f.get("module", "")
        impacts.append(
            {
                "title": f.get("title", ""),
                "affected_area": module.title() or "General",
                "impact": _MODULE_IMPACT_TEMPLATES.get(module, _DEFAULT_IMPACT),
                "severity": f.get("severity", "info"),
            }
        )
    return impacts
