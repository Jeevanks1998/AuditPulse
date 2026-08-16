"""
ai/

Everything AI-provider-backed lives here, one concern per file:

  provider.py           - low-level Anthropic call wrapper (call_ai / call_ai_json)
  recommendations.py     - the "ai" audit module's findings (services.ai_service, audit_service pipeline)
  executive_summary.py  - report-header summary paragraph
  priority.py            - deterministic fix-first ranking of findings
  business_impact.py    - technical findings translated into business-impact language
  action_plan.py         - horizon-grouped (quick win / short term / long term) remediation plan
  chatbot.py             - free-text Q&A grounded in one audit's own data

Every generator function here is independently safe to call — none of
them raise out to a caller on a provider outage or missing API key, except
ai.provider.call_ai / call_ai_json themselves, which are the one place
that's allowed to raise (AIProviderError) so each higher-level module can
decide its own fallback. See each module's docstring for its specific
fallback behavior.

services.ai_service is the thin service-layer wrapper that api/ routers
call into; nothing under api/ should import from ai.* directly.
"""

from ai.action_plan import ActionPlan, generate_action_plan
from ai.business_impact import generate_business_impact
from ai.chatbot import ask_about_audit
from ai.executive_summary import generate_executive_summary
from ai.priority import PrioritizedFinding, prioritize_findings, top_priorities
from ai.provider import AIProviderError, call_ai, call_ai_json, is_configured
from ai.recommendations import generate_recommendations

__all__ = [
    "ActionPlan",
    "generate_action_plan",
    "generate_business_impact",
    "ask_about_audit",
    "generate_executive_summary",
    "PrioritizedFinding",
    "prioritize_findings",
    "top_priorities",
    "AIProviderError",
    "call_ai",
    "call_ai_json",
    "is_configured",
    "generate_recommendations",
]
