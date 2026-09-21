"""
reports/json_report.py

Serializes a ReportPayload (§8) into the plain JSON-safe dict returned by
api/reports.py's `/{audit_id}/export.json` (score grid, findings, AI
summary/priorities/business-impact/action-plan) and cached to disk via
reports/report_storage.py's save_json/load_json.
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
        "analytics": payload.analytics,
        "cookie_evidence": payload.cookie_evidence,
        "network_evidence": payload.network_evidence,
        "screenshots": payload.screenshots,
        "executive_summary": payload.executive_summary,
        "business_impact": payload.business_impact,
        "action_plan": asdict(payload.action_plan),
        "priorities": [asdict(item) for item in payload.priorities],
    }


__all__ = ["to_json_report"]
