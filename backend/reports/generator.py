"""
ReportPayload: the one data model every report output is built from (JSON,
HTML, PDF, evidence ZIP, email attachments), so they never disagree.
build_report_payload() assembles it and adds the AI sections, which fall
back to templates if the AI is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ai.action_plan import ActionPlan, generate_action_plan
from ai.business_impact import generate_business_impact
from ai.executive_summary import generate_executive_summary
from ai.priority import PrioritizedFinding, top_priorities
from reports.consent_view import build_consent_view
from reports.cookie_view import build_cookie_inventory
from reports.journey_view import build_journey_view
from schemas.report import MODULE_LABELS, ScoreCell

# Same three severities used throughout audit.findings / pdf/charts.py's
# severity distribution / ai/priority.py's SEVERITY_RANK.
SEVERITIES = ("critical", "warning", "info")

# Score bands and labels (can't import pdf.theme here; it imports this module).
_SCORE_BAND_GOOD = 80
_SCORE_BAND_MID = 50
_STATUS_LABELS = {"good": "Healthy", "mid": "Needs attention", "bad": "Issues found"}


@dataclass
class ReportPayload:
    """The one object every report output is built from."""

    audit_id: int
    url: str
    overall: int
    generated_at: str
    score_grid: List[ScoreCell]
    findings: List[dict]
    share_url: Optional[str] = None

    # Raw module results, or None if the module didn't run.
    consent: Optional[dict] = None
    analytics: Optional[dict] = None

    # Cookie and network evidence for exports and email attachments.
    cookie_evidence: Optional[dict] = None
    network_evidence: Optional[dict] = None

    # Consent view shared by every report output.
    consent_view: Optional[dict] = None

    # Journey Map raw result and its view; None if it didn't run.
    journey: Optional[dict] = None
    journey_view: Optional[dict] = None

    # Cookie Scanner view; None if neither consent nor journey ran.
    cookie_inventory: Optional[dict] = None

    # Consent screenshots (see _build_screenshots).
    screenshots: List[dict] = field(default_factory=list)

    # Worked out once so every output shows the same numbers.
    severity_counts: Dict[str, int] = field(default_factory=dict)
    weakest_module: Optional[ScoreCell] = None
    overall_status: str = ""

    # AI sections (with template fallback).
    executive_summary: str = ""
    business_impact: List[dict] = field(default_factory=list)
    action_plan: ActionPlan = field(default_factory=ActionPlan)
    priorities: List[PrioritizedFinding] = field(default_factory=list)


def build_score_grid(breakdown: Dict[str, int]) -> List[ScoreCell]:
    """One cell per module that actually ran; never a placeholder score."""
    return [
        ScoreCell(
            module=module,
            label=MODULE_LABELS.get(module, module.replace("_", " ").title()),
            score=score,
            target_section=f"#{module}",
        )
        for module, score in breakdown.items()
    ]


def _severity_counts(findings: List[dict]) -> Dict[str, int]:
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        severity = finding.get("severity", "info")
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def _weakest_module(score_grid: List[ScoreCell]) -> Optional[ScoreCell]:
    if not score_grid:
        return None
    return min(score_grid, key=lambda cell: cell.score)


def _overall_status(overall: int) -> str:
    if overall >= _SCORE_BAND_GOOD:
        band = "good"
    elif overall >= _SCORE_BAND_MID:
        band = "mid"
    else:
        band = "bad"
    return _STATUS_LABELS[band]


def _build_screenshots(consent: Optional[dict]) -> List[dict]:
    """Consent screenshot URLs as [{key, url, label}]; keys start with "consent-"; missing ones are left out."""
    if not consent:
        return []
    slots = (
        ("consent-initial", "banner_screenshot_url", "Initial Banner"),
        ("consent-preferences", "preferences_screenshot_url", "Preferences Panel"),
        ("consent-reject", "reject_screenshot_url", "After Reject"),
        ("consent-accept", "accept_screenshot_url", "After Accept"),
    )
    return [
        {"key": key, "url": consent[field_name], "label": label}
        for key, field_name, label in slots
        if consent.get(field_name)
    ]


def _cookie_evidence(consent: Optional[dict]) -> Optional[dict]:
    """Cookie and consent-check evidence for exports. None when consent didn't run."""
    if not consent:
        return None
    return {
        "cookies_detected": consent.get("cookies_detected", []),
        "third_party_trackers": consent.get("third_party_trackers", []),
        "gdpr_checks": consent.get("gdpr_checks", {}),
        "gdpr_check_evidence": consent.get("gdpr_check_evidence", {}),
        "gdpr_compliant": consent.get("gdpr_compliant", False),
        "ccpa_checks": consent.get("ccpa_checks", {}),
        "ccpa_compliant": consent.get("ccpa_compliant", False),
        "applicability": consent.get("applicability", {}),
        "detected_region": consent.get("detected_region"),
        "region_confidence": consent.get("region_confidence"),
        "region_evidence": consent.get("region_evidence", []),
        "applicable_frameworks": consent.get("applicable_frameworks", []),
        "applicability_status": consent.get("applicability_status"),
        "consent_controls": consent.get("consent_controls", []),
        "cookies_before_consent": (consent.get("technical_scan") or {}).get("cookies_before_consent", {}),
        "technical_scan": consent.get("technical_scan", {}),
    }


def _network_evidence(analytics: Optional[dict], consent: Optional[dict] = None) -> Optional[dict]:
    """Analytics network evidence, plus consent's own classified requests when it ran."""
    if not analytics and not consent:
        return None
    out: dict = {}
    if analytics:
        out.update({
            "vendor_configs": analytics.get("vendor_configs", {}),
            "trackers_detected": analytics.get("trackers_detected", []),
            "runtime_tested": analytics.get("runtime_tested", False),
            "runtime_result": analytics.get("runtime_result"),
        })
    if consent:
        out["consent_network"] = (consent.get("technical_scan") or {}).get("network", {})
    return out


async def build_report_payload(
    *,
    audit_id: int,
    url: str,
    overall: int,
    generated_at: str,
    breakdown: Dict[str, int],
    findings: List[dict],
    share_url: Optional[str] = None,
    consent: Optional[dict] = None,
    analytics: Optional[dict] = None,
    journey: Optional[dict] = None,
) -> ReportPayload:
    """Builds the payload from already-loaded audit data, then adds the AI sections."""
    score_grid = build_score_grid(breakdown)

    executive_summary = await generate_executive_summary(url, overall, breakdown, findings)
    business_impact = await generate_business_impact(url, breakdown, findings)
    action_plan = await generate_action_plan(url, breakdown, findings)
    priorities = top_priorities(findings, breakdown)

    return ReportPayload(
        audit_id=audit_id,
        url=url,
        overall=overall,
        generated_at=generated_at,
        score_grid=score_grid,
        findings=findings,
        share_url=share_url,
        consent=consent,
        analytics=analytics,
        cookie_evidence=_cookie_evidence(consent),
        network_evidence=_network_evidence(analytics, consent),
        consent_view=(consent.get("report_view") if consent and consent.get("report_view")
                      else build_consent_view(consent)),
        journey=journey,
        journey_view=(journey.get("report_view") if journey and journey.get("report_view")
                      else build_journey_view(journey)),
        cookie_inventory=(build_cookie_inventory(consent, journey, url) if (consent or journey) else None),
        screenshots=_build_screenshots(consent),
        severity_counts=_severity_counts(findings),
        weakest_module=_weakest_module(score_grid),
        overall_status=_overall_status(overall),
        executive_summary=executive_summary,
        business_impact=business_impact,
        action_plan=action_plan,
        priorities=priorities,
    )


__all__ = ["ReportPayload", "build_report_payload", "build_score_grid"]
