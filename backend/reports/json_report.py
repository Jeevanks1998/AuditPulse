"""
reports/json_report.py

Turns a reports.generator.ReportPayload (dataclasses, not JSON-safe as-is)
into a plain, JSON-serializable dict — the shape returned by
GET /reports/{id}/export.json and what reports/report_storage.py writes
to disk. Kept as a single explicit shaping function rather than a generic
dataclass-to-dict walk so the exported schema is deliberate and versioned
(`schema_version`), independent of internal field names/order changing on
the dataclasses themselves.
"""

from __future__ import annotations

from typing import Any, Dict

from reports.generator import ReportPayload

JSON_REPORT_SCHEMA_VERSION = 1


def to_json_report(payload: ReportPayload) -> Dict[str, Any]:
    """Builds the exportable JSON document for one report."""
    return {
        "schema_version": JSON_REPORT_SCHEMA_VERSION,
        "audit_id": payload.audit_id,
        "url": payload.url,
        "overall": payload.overall,
        "generated_at": payload.generated_at,
        "share_url": payload.share_url,
        "score_grid": [
            {
                "module": cell.module,
                "label": cell.label,
                "score": cell.score,
                "target_section": cell.target_section,
            }
            for cell in payload.score_grid
        ],
        "findings": list(payload.findings),
        "executive_summary": payload.executive_summary,
        "priorities": [
            {
                "rank": p.rank,
                "module": p.module,
                "severity": p.severity,
                "title": p.title,
                "description": p.description,
                "recommendation": p.recommendation,
                "effort": p.effort,
            }
            for p in payload.priorities
        ],
        "business_impact": list(payload.business_impact),
        "action_plan": (
            {
                "quick_wins": payload.action_plan.quick_wins,
                "short_term": payload.action_plan.short_term,
                "long_term": payload.action_plan.long_term,
            }
            if payload.action_plan
            else None
        ),
        # Single canonical report data (§8) — same shape the PDF, evidence
        # ZIP, and POC email attachments all read off `payload` directly.
        "analytics": payload.analytics,
        "consent": payload.consent,
        "screenshots": list(payload.screenshots),
        "cookie_evidence": dict(payload.cookie_evidence),
        "network_evidence": dict(payload.network_evidence),
    }
