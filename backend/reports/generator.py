"""
reports/generator.py

Builds the full, in-memory report payload for one completed Audit —
the score grid (report.html's radar chart, see assets/js/report.js ->
Charts.renderRadar), the findings, and the AI-generated layer on top
(executive summary, prioritized findings, business impact, action plan).
This is the one place that assembles all of that into a single shape;
reports/json_report.py and reports/html_report.py both take a
`ReportPayload` from here and just re-render it in a different format,
and reports/report_storage.py persists whatever they produce.

services.report_service is the thin, request-facing layer that calls in
here — nothing under api/ should build a report payload itself.

The AI section is additive and best-effort: `build_report_payload` always
returns the score grid + findings even if every AI call fails, since
ai.* itself already falls back to heuristic content rather than raising
(see ai/provider.py's docstring) — there's no failure mode left here to
handle, but `include_ai=False` is available for callers that want the
fast, AI-free path (e.g. a live preview) regardless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ai import (
    ActionPlan,
    generate_action_plan,
    generate_business_impact,
    generate_executive_summary,
    top_priorities,
)
from ai.priority import PrioritizedFinding

MODULE_LABELS = {
    "seo": "SEO",
    "performance": "Performance",
    "accessibility": "Accessibility",
    "security": "Security",
    "ux": "UX",
    "images": "Images",
    "links": "Links",
    "mobile": "Mobile",
    "forms": "Forms",
    "consent": "Consent",
    "analytics": "Analytics",
    "ai": "AI Review",
}


@dataclass
class ScoreCell:
    module: str
    label: str
    score: int
    target_section: str


@dataclass
class ReportPayload:
    audit_id: int
    url: str
    overall: int
    generated_at: str
    score_grid: List[ScoreCell] = field(default_factory=list)
    findings: List[dict] = field(default_factory=list)
    executive_summary: Optional[str] = None
    priorities: List[PrioritizedFinding] = field(default_factory=list)
    business_impact: List[dict] = field(default_factory=list)
    action_plan: Optional[ActionPlan] = None
    share_url: Optional[str] = None

    # --------------------------------------------------------------------
    # Single canonical report data (requirements §8) — the same shapes
    # api/audit.py's /consent and /analytics endpoints already return
    # (schemas.audit.ConsentOut / AnalyticsOut, as plain dicts so this
    # module stays free of any SQLAlchemy/Pydantic import), now folded
    # into the one payload that the Dashboard, HTML report, PDF report
    # and POC Email all build from — no separate scoring/detection logic
    # per output, per §8's own instruction.
    # --------------------------------------------------------------------
    analytics: Optional[dict] = None
    consent: Optional[dict] = None
    # Every screenshot captured for this audit, evidence-package-ready:
    # [{"key": "consent-initial", "label": "Initial consent banner",
    #   "path": "<abs/relative path on disk>", "url": "/screenshots/.."}]
    screenshots: List[dict] = field(default_factory=list)
    # Cookies captured before consent / after Reject / after Accept
    # (consent.runtime's ConsentStateCapture.cookies, §4.4).
    cookie_evidence: dict = field(default_factory=dict)
    # Network requests captured at the same three checkpoints, plus the
    # analytics runtime pass's captured request log (§3.3/§4.4).
    network_evidence: dict = field(default_factory=dict)


def build_score_grid(breakdown: Dict[str, int]) -> List[ScoreCell]:
    return [
        ScoreCell(
            module=key,
            label=MODULE_LABELS.get(key, key.title()),
            score=value,
            target_section=f"section-{key}",
        )
        for key, value in breakdown.items()
    ]


async def build_report_payload(
    *,
    audit_id: int,
    url: str,
    overall: int,
    generated_at: str,
    breakdown: Dict[str, int],
    findings: List[dict],
    share_url: Optional[str] = None,
    include_ai: bool = True,
    consent: Optional[dict] = None,
    analytics: Optional[dict] = None,
) -> ReportPayload:
    """
    Assembles the full report payload for one audit. `breakdown` and
    `findings` are read straight off the Audit row (Audit.breakdown /
    Audit.findings) by the caller — this function does no DB access itself,
    so it's equally usable from a request handler, a background job, or a
    test.

    `consent`/`analytics` are the same plain-dict shape schemas.audit's
    ConsentOut/AnalyticsOut already produce (services.report_service passes
    `.model_dump()` of the Consent/Analytics rows it already fetches for
    this audit) — optional, since a given audit may not have run those
    modules (see config.constants.AUDIT_MODULES).
    """
    payload = ReportPayload(
        audit_id=audit_id,
        url=url,
        overall=overall,
        generated_at=generated_at,
        score_grid=build_score_grid(breakdown),
        findings=findings,
        share_url=share_url,
        consent=consent,
        analytics=analytics,
    )
    _attach_evidence(payload, consent=consent, analytics=analytics)

    if not include_ai:
        return payload

    payload.executive_summary = await generate_executive_summary(url, overall, breakdown, findings)
    payload.priorities = top_priorities(findings, breakdown)
    payload.business_impact = await generate_business_impact(url, breakdown, findings)
    payload.action_plan = await generate_action_plan(url, breakdown, findings)
    return payload


def _attach_evidence(payload: ReportPayload, *, consent: Optional[dict], analytics: Optional[dict]) -> None:
    """
    Populates `payload.screenshots` / `cookie_evidence` / `network_evidence`
    from the consent/analytics dicts — the evidence §5/§7.1/§8 both need,
    kept in one place so pdf/, reports/evidence.py and the email
    attachments builder all read the exact same shape instead of each
    re-deriving it from the raw ConsentOut/AnalyticsOut dict differently.
    """
    screenshots: List[dict] = []

    if consent:
        for key, label, url_field in (
            ("consent-initial", "Initial consent banner", "banner_screenshot_url"),
            ("consent-preferences", "Personalize / Manage Preferences", "preferences_screenshot_url"),
            ("consent-reject", "After Reject", "reject_screenshot_url"),
            ("consent-accept", "After Accept", "accept_screenshot_url"),
        ):
            shot_url = consent.get(url_field)
            if shot_url:
                screenshots.append({"key": key, "label": label, "url": shot_url})

        runtime_result = consent.get("runtime_result") or {}
        cookie_evidence = {}
        network_evidence = {}
        for phase, capture_key in (
            ("before_consent", "before_consent"),
            ("after_reject", "after_reject"),
            ("after_accept", "after_accept"),
        ):
            capture = runtime_result.get(capture_key) or {}
            cookie_evidence[phase] = capture.get("cookies", [])
            network_evidence[phase] = capture.get("requests", [])
        payload.cookie_evidence = cookie_evidence
        payload.network_evidence.update(network_evidence)

    if analytics:
        runtime_result = analytics.get("runtime_result") or {}
        vendors = runtime_result.get("vendors") or {}
        analytics_requests = []
        for vendor in vendors.values():
            for req_url in vendor.get("request_urls", []) or []:
                analytics_requests.append({"vendor": vendor.get("vendor_name"), "url": req_url})
        payload.network_evidence["analytics_runtime"] = analytics_requests

    payload.screenshots = screenshots
