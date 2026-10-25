"""
AI features. Each file does one job:

  provider.py          - calls the AI provider (Groq or Anthropic)
  recommendations.py   - AI findings for the "ai" module
  executive_summary.py - summary paragraph at the top of the report
  priority.py          - fix-first ranking of findings (rule-based, no AI)
  business_impact.py   - findings explained in business terms
  action_plan.py       - quick wins / short term / long term plan
  chatbot.py           - questions and answers about one audit

Only provider.py raises errors; everything else falls back to a fixed
template, so AI problems never fail an audit. api/ code goes through
services.ai_service, not this package directly.
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
