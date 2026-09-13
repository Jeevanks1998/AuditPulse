"""
reports/generator.py

Canonical ReportPayload data model (§8: "one canonical data model for
dashboard/report/PDF/email"). Every export surface — the JSON export
(reports/json_report.py), the standalone HTML export
(reports/html_report.py), the PDF export (pdf/pdf_generator.py and the
rest of pdf/), the evidence ZIP (reports/evidence.py), and the POC email
attachments (emailer/attachments.py) — is built from one ReportPayload
instance, so score/finding/evidence content is computed exactly once per
export and can never drift between formats.

`build_report_payload` is the only place that assembles one: it takes the
already-fetched Audit/Consent/Analytics data (services.report_service has
no idea this module exists beyond that one call) and layers the
AI-enriched executive_summary/business_impact/action_plan/priorities on
top via ai/* — each of which independently falls back to a deterministic
heuristic on a provider outage rather than raising (see ai/__init__.py),
so a missing/failed ANTHROPIC_API_KEY degrades report quality, it never
breaks report generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ai.action_plan import ActionPlan, generate_action_plan
from ai.business_impact import generate_business_impact
from ai.executive_summary import generate_executive_summary
from ai.priority import PrioritizedFinding, top_priorities
from schemas.report import MODULE_LABELS, ScoreCell

# Same three severities used throughout audit.findings / pdf/charts.py's
# severity distribution / ai/priority.py's SEVERITY_RANK.
SEVERITIES = ("critical", "warning", "info")

# Mirrors pdf.theme.SCORE_BAND_LABELS / assets/js/dashboard.js's
# healthBadgeLabel wording, and config.constants.SCORE_BANDS' thresholds —
# reports/generator.py can't import pdf.theme (pdf/* imports *this*
# module), so the same good/mid/bad bands and labels are re-declared here
# as the one source every export format (not just the PDF) reads
# `overall_status` from.
_SCORE_BAND_GOOD = 80
_SCORE_BAND_MID = 50
_STATUS_LABELS = {"good": "Healthy", "mid": "Needs Attention", "bad": "Issues Found"}


@dataclass
class ReportPayload:
    """The one object every report export surface renders from."""

    audit_id: int
    url: str
    overall: int
    generated_at: str
    score_grid: List[ScoreCell]
    findings: List[dict]
    share_url: Optional[str] = None

    # Raw module results (ConsentOut / AnalyticsOut .model_dump()), or None
    # if that module didn't run for this audit.
    consent: Optional[dict] = None
    analytics: Optional[dict] = None

    # Evidence split out of consent/analytics for standalone export (the
    # POC email's "cookie_evidence"/"network_evidence" attachment keys,
    # reports/evidence.py's ZIP) — see _cookie_evidence/_network_evidence
    # below for exactly what each carries.
    cookie_evidence: Optional[dict] = None
    network_evidence: Optional[dict] = None

    # Flattened from ConsentOut's four *_screenshot_url computed fields —
    # see _build_screenshots below.
    screenshots: List[dict] = field(default_factory=list)

    # Derived once here so every consumer (PDF metric cards, JSON export,
    # HTML export) reads the same numbers instead of recomputing them.
    severity_counts: Dict[str, int] = field(default_factory=dict)
    weakest_module: Optional[ScoreCell] = None
    overall_status: str = ""

    # AI-enriched layer (ai/*) — see this module's docstring for the
    # fallback contract.
    executive_summary: str = ""
    business_impact: List[dict] = field(default_factory=list)
    action_plan: ActionPlan = field(default_factory=ActionPlan)
    priorities: List[PrioritizedFinding] = field(default_factory=list)


def build_score_grid(breakdown: Dict[str, int]) -> List[ScoreCell]:
    """Only modules actually present in `breakdown` get a cell — never a
    placeholder score for a module that wasn't scanned (§3.4/§9: "No Dummy
    Data Rule")."""
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
    """Flattens ConsentOut's four *_screenshot_url computed fields into the
    [{key, url, label}] list every consumer of ReportPayload.screenshots
    (pdf/evidence.py's Consent Evidence grid, emailer/attachments.py's
    "consent_screenshots" attachment, reports/evidence.py's ZIP) expects.
    Keys are prefixed "consent-" so pdf/evidence.py can pick out the
    consent-flow shots specifically; a bare key with no matching URL is
    omitted rather than included with url=None."""
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
    """Raw cookie/tracker/consent-check evidence split out of the summarized
    `consent` dict, for the POC email's standalone "cookie_evidence"
    attachment and the evidence ZIP — None (not an empty dict) when consent
    didn't run, matching every other optional payload field's contract."""
    if not consent:
        return None
    return {
        "cookies_detected": consent.get("cookies_detected", []),
        "third_party_trackers": consent.get("third_party_trackers", []),
        "gdpr_checks": consent.get("gdpr_checks", {}),
        "gdpr_compliant": consent.get("gdpr_compliant", False),
        "ccpa_checks": consent.get("ccpa_checks", {}),
        "ccpa_compliant": consent.get("ccpa_compliant", False),
    }


def _network_evidence(analytics: Optional[dict]) -> Optional[dict]:
    """Raw runtime/vendor network evidence split out of `analytics`, same
    reasoning as `_cookie_evidence` above."""
    if not analytics:
        return None
    return {
        "vendor_configs": analytics.get("vendor_configs", {}),
        "trackers_detected": analytics.get("trackers_detected", []),
        "runtime_tested": analytics.get("runtime_tested", False),
        "runtime_result": analytics.get("runtime_result"),
    }


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
) -> ReportPayload:
    """Assembles the one canonical payload (§8) every export/dashboard
    surface reads from. `findings`/`breakdown`/`consent`/`analytics` are
    passed in already-fetched (this module has no idea SQLAlchemy exists,
    per services/report_service.py's docstring) — this only derives the
    score grid, evidence splits, and screenshot list from them, then adds
    the AI-enriched layer on top."""
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
        network_evidence=_network_evidence(analytics),
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
