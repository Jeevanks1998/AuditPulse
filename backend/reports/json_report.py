"""
Turns a ReportPayload into the JSON export (scores, findings, AI sections).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from reports.generator import ReportPayload


def to_json_report(payload: ReportPayload) -> Dict[str, Any]:
    weakest = payload.weakest_module
    return {
        "audit_id": payload.audit_id,
        "url": payload.url,
        "overall": payload.overall,
        "overall_status": payload.overall_status,
        "generated_at": payload.generated_at,
        "share_url": payload.share_url,
        "score_grid": [cell.model_dump() for cell in payload.score_grid],
        "findings": payload.findings,
        "severity_counts": payload.severity_counts,
        "weakest_module": weakest.model_dump() if weakest else None,
        "consent": payload.consent,
        "consent_view": payload.consent_view,
        "journey_view": payload.journey_view,
        "cookie_inventory": payload.cookie_inventory,
        "analytics": payload.analytics,
        "cookie_evidence": payload.cookie_evidence,
        "network_evidence": payload.network_evidence,
        "screenshots": payload.screenshots,
        "executive_summary": payload.executive_summary,
        "business_impact": payload.business_impact,
        "action_plan": asdict(payload.action_plan),
        "priorities": [asdict(item) for item in payload.priorities],
        "accepted_findings": payload.accepted_findings,
        "raw_overall": payload.raw_overall,
    }


__all__ = ["to_json_report"]
