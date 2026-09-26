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
from typing import Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from config.compliance_profiles import (
    ComplianceStatus,
    build_ccpa_final_assessment,
    build_gdpr_final_assessment,
)
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


class ComplianceStatusOut(BaseModel):
    """
    The only shape a regional compliance verdict takes once it reaches
    the browser: which framework was evaluated, and one status out of
    ComplianceStatus. See config.compliance_profiles for how that status
    is derived — the internal requirements feeding into it (score
    floors, runtime-verification requirements, which team owns them)
    stop at the backend; this model has no field for any of that.
    """
    framework: Optional[str] = None
    status: ComplianceStatus


class ConsentOut(BaseModel):
    """Result of the consent-module scan (services.audit_service._write_consent_result)."""

    has_cookie_banner: bool
    banner_blocks_scripts_pre_consent: bool

    # Region detection (consent.region_detector.detect_region, persisted on
    # models.consent.Consent) — which region this audit was evaluated
    # against and why. detected_region is the coarse REGION_* bucket
    # ("EU", "UK", "US-CA", "UNKNOWN", ...); detected_country is the more
    # specific display label (e.g. "France"). compliance_framework is the
    # single regional framework (if any) that applied — "GDPR" /
    # "UK GDPR" / "Swiss FADP" / "CCPA/CPRA" / None. gdpr_assessed /
    # ccpa_assessed say whether that family of checks applied to this
    # audit at all — check these before treating gdpr_compliant/
    # ccpa_compliant below as a real verdict rather than "not assessed".
    detected_region: str = "UNKNOWN"
    detected_country: Optional[str] = None
    compliance_framework: Optional[str] = None
    region_confidence: str = "none"
    region_detection_source: str = "None"
    region_detection_reason: str = ""
    gdpr_assessed: bool = False
    ccpa_assessed: bool = False

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

    @computed_field  # type: ignore[misc]
    @property
    def gdpr_status(self) -> ComplianceStatusOut:
        """
        The browser-facing GDPR-family verdict — see
        config.compliance_profiles.build_gdpr_final_assessment. Everything
        this depends on (the internal score floor, the runtime-
        verification requirement) lives in that private module, not here.

        `gdpr_checks` being empty is this schema's only available signal
        for "no regional framework applied to this audit" until the
        detected region/framework name is itself persisted on the Consent
        row (gdpr_compliant is a non-nullable column today, so it can't
        yet distinguish "not applicable" from a real False) — see the
        migration note on consent.consent_score.ConsentSummary.gdpr_compliant.
        """
        applicable = bool(self.gdpr_checks)
        assessment = build_gdpr_final_assessment(
            framework_name="GDPR",
            applicable=applicable,
            compliant=self.gdpr_compliant if applicable else None,
            consent_score=self.consent_score,
            runtime_tested=self.runtime_tested,
        )
        return ComplianceStatusOut(framework=assessment.framework, status=assessment.status)

    @computed_field  # type: ignore[misc]
    @property
    def ccpa_status(self) -> ComplianceStatusOut:
        """The browser-facing CCPA/CPRA verdict — see gdpr_status above for the same caveat on applicability."""
        applicable = bool(self.ccpa_checks)
        assessment = build_ccpa_final_assessment(
            applicable=applicable,
            compliant=self.ccpa_compliant if applicable else None,
            consent_score=self.consent_score,
            runtime_tested=self.runtime_tested,
        )
        return ComplianceStatusOut(framework=assessment.framework, status=assessment.status)


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
