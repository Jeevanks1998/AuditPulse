"""
schemas/audit.py

Request/response models for api/audit.py: starting a run, polling its
progress, and reading back a result. `AuditOut` is also reused as the
list-item shape for dashboard "recent audits" (api/dashboard.py),
history pagination (api/history.py), the schedule "run now" response
(api/scheduler.py), and the audit list embedded in a settings export
(api/settings.py) — one canonical serialization of an Audit row for
every router that needs it.
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from config.constants import DEFAULT_MAX_PAGES, MAX_PAGES_LIMIT, MIN_PAGES_LIMIT


class AuditCreate(BaseModel):
    url: str
    depth: str = Field(default="homepage", pattern="^(homepage|full)$")
    max_pages: int = Field(default=DEFAULT_MAX_PAGES, ge=MIN_PAGES_LIMIT, le=MAX_PAGES_LIMIT)
    # validate_default=True closes a gap where Pydantic v2 normally skips
    # validating a field's *default* value: without it, sending no
    # "modules" key at all silently fell back to `[]` and bypassed the
    # min_length=1 check that an explicit `"modules": []` correctly
    # triggers — producing a "successful" audit that silently skipped
    # consent/analytics/AI scoring. Now both paths raise the same error.
    modules: List[str] = Field(default_factory=list, min_length=1, validate_default=True)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Please provide a valid website URL.")
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        if not urlparse(v).netloc:
            raise ValueError("Please provide a valid website URL.")
        return v


class AuditOut(BaseModel):
    id: int
    url: str
    label: str
    depth: str
    status: str
    current_step: Optional[str] = None
    percent: int
    overall_score: Optional[int] = None
    breakdown: Optional[dict] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AuditProgressOut(BaseModel):
    id: int
    status: str
    current_step: Optional[str] = None
    percent: int
    overall_score: Optional[int] = None


class ConsentOut(BaseModel):
    """Result of the consent-module scan (services.audit_service._write_consent_result)."""

    has_cookie_banner: bool
    banner_blocks_scripts_pre_consent: bool
    gdpr_compliant: bool
    # Per-check breakdown behind gdpr_compliant — see
    # consent.consent_score.GDPR_CHECK_ORDER for the ten keys and their
    # order. Each value is True/False/None ("not evaluated"). Empty on
    # audits written before this field existed.
    gdpr_checks: Dict[str, Optional[bool]] = Field(default_factory=dict)
    # Structured evidence for whichever gdpr_checks entries have it — sparse,
    # keyed the same as gdpr_checks. See consent.consent_score.GdprCheck
    # .evidence / models.consent.Consent.gdpr_check_evidence. Shape per
    # entry: {"summary": str, "items": [str, ...], "items_label": str}.
    gdpr_check_evidence: Dict[str, dict] = Field(default_factory=dict)
    ccpa_compliant: bool
    # Per-check breakdown behind ccpa_compliant — see
    # consent.consent_score.CCPA_CHECK_ORDER for the six keys and their
    # order. Each value is True/False/None ("not evaluated"). Empty on
    # audits written before this field existed.
    ccpa_checks: Dict[str, Optional[bool]] = Field(default_factory=dict)
    # Region + applicable frameworks (consent.region). Empty on
    # audits written before Phase 1 — the frontend then shows its legacy view.
    applicability: Dict[str, Any] = Field(default_factory=dict)
    # Framework-neutral technical consent scan (banner, control inventory,
    # technical checks, classified network/cookie evidence).
    technical_scan: Dict[str, Any] = Field(default_factory=dict)
    # Region engine output + consent-control inventory (Phase 2 columns).
    detected_region: str = "UNKNOWN"
    region_confidence: str = "low"
    region_evidence: List[str] = Field(default_factory=list)
    applicable_frameworks: List[str] = Field(default_factory=list)
    applicability_status: str = "not_determined"
    consent_controls: List[dict] = Field(default_factory=list)
    privacy_policy_found: bool
    privacy_policy_url: Optional[str] = None
    cookies_detected: List[dict] = Field(default_factory=list)
    third_party_trackers: List[str] = Field(default_factory=list)
    consent_score: int
    banner_screenshot_path: Optional[str] = Field(default=None, exclude=True)
    preferences_screenshot_path: Optional[str] = Field(default=None, exclude=True)
    reject_screenshot_path: Optional[str] = Field(default=None, exclude=True)
    accept_screenshot_path: Optional[str] = Field(default=None, exclude=True)

    # consent.runtime's click-through verdicts — runtime_tested gates
    # whether the frontend should show reject_blocks_tracking /
    # accept_allows_tracking / personalize_exposes_controls as real
    # pass/fail results rather than "not tested" (see report.js's
    # renderConsent, which checks consent.runtimeTested before rendering
    # those three check items).
    runtime_available: bool = False
    runtime_tested: bool = False
    runtime_result: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[misc]
    @property
    def banner_screenshot_url(self) -> Optional[str]:
        """
        `/screenshots/<file>.png` — served by the StaticFiles mount in
        main.py. None when Playwright wasn't installed, capture was
        disabled, or the capture failed (no banner found / site
        unreachable) — the frontend should render a "no screenshot
        available" state rather than a broken <img> in that case.
        """
        return _screenshot_url(self.banner_screenshot_path)

    @computed_field  # type: ignore[misc]
    @property
    def preferences_screenshot_url(self) -> Optional[str]:
        """Screenshot of the Personalize/Manage Preferences panel, if the runtime pass found and opened one."""
        return _screenshot_url(self.preferences_screenshot_path)

    @computed_field  # type: ignore[misc]
    @property
    def reject_screenshot_url(self) -> Optional[str]:
        """Screenshot taken right after the runtime pass clicked Reject, if it found a reject button."""
        return _screenshot_url(self.reject_screenshot_path)

    @computed_field  # type: ignore[misc]
    @property
    def accept_screenshot_url(self) -> Optional[str]:
        """Screenshot taken right after the runtime pass clicked Accept (separate clean browser context)."""
        return _screenshot_url(self.accept_screenshot_path)

    @field_validator("applicability", "technical_scan", "gdpr_checks", "gdpr_check_evidence", "ccpa_checks",
                     mode="before")
    @classmethod
    def _none_to_dict(cls, value):
        return value or {}

    @field_validator("region_evidence", "applicable_frameworks", "consent_controls",
                     "cookies_detected", "third_party_trackers", mode="before")
    @classmethod
    def _none_to_list(cls, value):
        return value or []

    @field_validator("detected_region", mode="before")
    @classmethod
    def _region_default(cls, value):
        return value or "UNKNOWN"

    @field_validator("region_confidence", mode="before")
    @classmethod
    def _confidence_default(cls, value):
        return value or "low"

    @field_validator("applicability_status", mode="before")
    @classmethod
    def _status_default(cls, value):
        return value or "not_determined"

    @computed_field  # type: ignore[misc]
    @property
    def report_view(self) -> Optional[Dict[str, Any]]:
        """
        Phase 4: the one consent presentation model (reports.consent_view)
        that the dashboard, report page, PDF, JSON export and evidence ZIP
        all render from — tiles, frameworks (assessed / not assessed),
        control inventory, classified network + cookie evidence, the four
        screenshot slots and the scan pipeline.
        """
        from reports.consent_view import build_consent_view  # local: avoids an import cycle

        data = {
            "has_cookie_banner": self.has_cookie_banner,
            "gdpr_checks": self.gdpr_checks,
            "gdpr_check_evidence": self.gdpr_check_evidence,
            "ccpa_checks": self.ccpa_checks,
            "consent_score": self.consent_score,
            "runtime_result": self.runtime_result,
            "applicability": self.applicability,
            "technical_scan": self.technical_scan,
            "detected_region": self.detected_region,
            "region_confidence": self.region_confidence,
            "region_evidence": self.region_evidence,
            "applicable_frameworks": self.applicable_frameworks,
            "consent_controls": self.consent_controls,
            "banner_screenshot_url": self.banner_screenshot_url,
            "preferences_screenshot_url": self.preferences_screenshot_url,
            "reject_screenshot_url": self.reject_screenshot_url,
            "accept_screenshot_url": self.accept_screenshot_url,
        }
        return build_consent_view(data)


def _screenshot_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"/screenshots/{os.path.basename(path)}"


class AnalyticsOut(BaseModel):
    """Result of the analytics-module scan (services.audit_service._run_analytics_checks)."""

    trackers_detected: List[str] = Field(default_factory=list)
    tag_manager_detected: bool
    gtm_container_id: Optional[str] = None
    ga_measurement_id: Optional[str] = None

    # Actual detected configuration per vendor ({vendor_key: [ids]}) —
    # covers Adobe, Piano, Clarity, Hotjar, Meta Pixel, LinkedIn, TikTok,
    # plus the full GA4/GTM ID lists. Only keys for vendors that were
    # actually detected are present; a vendor detected with no
    # extractable ID is present with an empty list, never omitted in
    # favor of a placeholder. See analytics.analytics_score.VENDOR_ID_ATTR
    # / TRACKER_DISPLAY_NAMES for the key -> display-name mapping.
    vendor_configs: Dict[str, List[str]] = Field(default_factory=dict)

    # Phase 2 — full-site analytics. Empty defaults on a homepage-only
    # audit; populated when the audit's depth was "full". See
    # analytics.analytics_score.PageAnalyticsResult / compute_site_coverage
    # / check_cross_page_consistency for what builds each of these.
    page_results: List[dict] = Field(default_factory=list)
    site_coverage: Dict[str, int] = Field(default_factory=dict)
    cross_page_findings: List[dict] = Field(default_factory=list)

    data_layer_present: bool
    pageview_events_found: int
    custom_events_found: int
    analytics_score: int

    # analytics.runtime's live Page View/Scroll/Click verdicts, per vendor
    # — see AnalyticsRuntimeResult.vendors. runtime_tested gates whether
    # the frontend's per-vendor table should render real pass/fail state
    # or a "not tested" placeholder.
    runtime_available: bool = False
    runtime_tested: bool = False
    runtime_result: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)


class AuditStatsOut(BaseModel):
    total_audits: int
    seo_issues: int
    performance_score: int
    critical_issues: int
    overall: int
    breakdown: dict


class JourneyOut(BaseModel):
    """Result of the Customer Journey scan (journey/ — services.audit_service._run_journey_checks)."""

    available: bool = False
    error: Optional[str] = None
    scan_id: Optional[str] = None
    consent_state: Optional[str] = None
    journey_score: Optional[int] = None
    health: Dict[str, Any] = Field(default_factory=dict)
    pages: List[dict] = Field(default_factory=list)
    interactions: List[dict] = Field(default_factory=list)
    forms: List[dict] = Field(default_factory=list)
    downloads: List[dict] = Field(default_factory=list)
    journey_map: Dict[str, Any] = Field(default_factory=dict)
    tracking: Dict[str, Any] = Field(default_factory=dict)
    findings: List[dict] = Field(default_factory=list)
    limits: Dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("health", "journey_map", "tracking", "limits", mode="before")
    @classmethod
    def _none_to_dict(cls, value):
        return value or {}

    @field_validator("pages", "interactions", "forms", "downloads", "findings", mode="before")
    @classmethod
    def _none_to_list(cls, value):
        return value or []

    @computed_field  # type: ignore[misc]
    @property
    def report_view(self) -> Optional[Dict[str, Any]]:
        """The one journey presentation model (reports.journey_view) every surface renders."""
        from reports.journey_view import build_journey_view  # local: avoids an import cycle

        return build_journey_view({
            "available": self.available, "error": self.error, "scan_id": self.scan_id,
            "consent_state": self.consent_state, "health": self.health, "pages": self.pages,
            "interactions": self.interactions, "forms": self.forms, "downloads": self.downloads,
            "journey_map": self.journey_map, "tracking": self.tracking, "findings": self.findings,
            "limits": self.limits, "started_at": self.started_at, "finished_at": self.finished_at,
        })
