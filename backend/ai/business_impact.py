"""
ai/business_impact.py

Translates technical findings into the language a business stakeholder
reads a report for: not "missing Referrer-Policy header" but what that
costs the business (trust, conversions, legal exposure) if left unfixed.
Feeds reports/generator.py's `business_impact` field, shown alongside the
raw findings list rather than replacing it — report.html still needs the
technical detail for whoever actually implements the fix.

Same fallback contract as the rest of ai/: never raises out of
`generate_business_impact`, falls back to a deterministic template keyed
off each finding's module when the provider is unavailable or fails.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from config.logging import logger
from ai.provider import AIProviderError, call_ai_json

MAX_IMPACT_ITEMS = 5

# Used by the heuristic fallback to phrase impact without an AI call.
_MODULE_IMPACT_TEMPLATES: Dict[str, str] = {
    "seo": "Lower search visibility means fewer visitors ever reach the site organically.",
    "performance": "Slower pages increase bounce rate and lower conversion, especially on mobile.",
    "accessibility": "Excludes users with disabilities and carries legal (ADA/WCAG) exposure.",
    "security": "Leaves visitor data and site trust exposed to compromise or defacement.",
    "mobile": "A broken mobile experience turns away the majority of typical web traffic.",
    "forms": "Friction or failures in forms directly reduce lead and signup conversion.",
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
    """
    Returns up to MAX_IMPACT_ITEMS dicts of shape
    {title, impact, affected_area, severity} — one per notable finding,
    written for a business (not technical) reader.
    """
    findings = findings or []
    try:
        return await _impact_from_ai(url, breakdown, findings)
    except AIProviderError as exc:
        logger.warning(f"ai.business_impact: falling back to heuristic impact statements: {exc}")
        return _heuristic_impact(findings)


# --------------------------------------------------------------------------
# AI-backed path
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Heuristic fallback
# --------------------------------------------------------------------------
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
