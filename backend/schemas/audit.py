"""
Request/response models for audits. AuditOut is the shared shape for an audit in every list.
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from config.constants import DEFAULT_MAX_PAGES, MAX_PAGES_LIMIT, MIN_PAGES_LIMIT


def normalize_audit_url(v: str) -> str:
    """Used by audits and schedules: adds https://, needs a host, public sites only (SSRF protection)."""
    v = (v or "").strip()
    if not v or len(v) > 500:
        raise ValueError("Please provide a valid website URL.")
    if not v.startswith(("http://", "https://")):
        v = "https://" + v
    if not urlparse(v).netloc:
        raise ValueError("Please provide a valid website URL.")
    from utils.net_guard import BlockedTargetError, check_url
    try:
        check_url(v)
    except BlockedTargetError as exc:
        raise ValueError(str(exc)) from exc
    return v


class AuditCreate(BaseModel):
    url: str
    depth: str = Field(default="homepage", pattern="^(homepage|full)$")
    max_pages: int = Field(default=DEFAULT_MAX_PAGES, ge=MIN_PAGES_LIMIT, le=MAX_PAGES_LIMIT)
    # validate_default=True so a missing "modules" key fails the same as an empty list.
    modules: List[str] = Field(default_factory=list, min_length=1, validate_default=True)
    # "auto" or empty = detect from the site; otherwise the region whose rules apply.
    target_region: Optional[str] = None

    @field_validator("target_region")
    @classmethod
    def normalize_target_region(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        key = v.strip().upper()
        if key in ("", "AUTO"):
            return None
        if key not in ("EU", "UK", "US-CA", "IN"):
            raise ValueError("Target region must be one of: auto, EU, UK, US-CA, IN.")
        return key

    @field_validator("url")
    @classmethod
    def normalize_url(cls, v: str) -> str:
        return normalize_audit_url(v)


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
    target_region: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AuditProgressOut(BaseModel):
    id: int
    status: str
    current_step: Optional[str] = None
    percent: int
    overall_score: Optional[int] = None


class ConsentOut(BaseModel):
    """Consent results."""

    has_cookie_banner: bool
    banner_blocks_scripts_pre_consent: bool
    gdpr_compliant: bool
    # GDPR check -> True / False / None (not tested). Empty for older audits.
    gdpr_checks: Dict[str, Optional[bool]] = Field(default_factory=dict)
    # Evidence per GDPR check: {"summary", "items", "items_label"}.
    gdpr_check_evidence: Dict[str, dict] = Field(default_factory=dict)
    ccpa_compliant: bool
    # CCPA check -> True / False / None (not tested). Empty for older audits.
    ccpa_checks: Dict[str, Optional[bool]] = Field(default_factory=dict)
    # Region and laws assessed. Empty for older audits (the frontend shows the older view).
    applicability: Dict[str, Any] = Field(default_factory=dict)
    # Law-neutral scan: banner, buttons, checks and evidence.
    technical_scan: Dict[str, Any] = Field(default_factory=dict)
    # Detected region and banner buttons.
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

    # runtime_tested: show Accept/Reject results as real pass/fail instead of "not tested".
    runtime_available: bool = False
    runtime_tested: bool = False
    runtime_result: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[misc]
    @property
    def banner_screenshot_url(self) -> Optional[str]:
        """`/screenshots/<file>.png`, or None when there's no screenshot."""
        return _screenshot_url(self.banner_screenshot_path)

    @computed_field  # type: ignore[misc]
    @property
    def preferences_screenshot_url(self) -> Optional[str]:
        """Settings panel screenshot, if it was opened."""
        return _screenshot_url(self.preferences_screenshot_path)

    @computed_field  # type: ignore[misc]
    @property
    def reject_screenshot_url(self) -> Optional[str]:
        """Screenshot after Reject, if Reject was found."""
        return _screenshot_url(self.reject_screenshot_path)

    @computed_field  # type: ignore[misc]
    @property
    def accept_screenshot_url(self) -> Optional[str]:
        """Screenshot after Accept."""
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
        """The shared consent view (see reports.consent_view)."""
        from reports.consent_view import build_consent_view  # local import avoids a cycle

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
    """Analytics results."""

    trackers_detected: List[str] = Field(default_factory=list)
    tag_manager_detected: bool
    gtm_container_id: Optional[str] = None
    ga_measurement_id: Optional[str] = None

    # IDs per detected tool ({"ga4": [...]}). Only detected tools appear.
    vendor_configs: Dict[str, List[str]] = Field(default_factory=dict)

    # Full-site results; empty for homepage audits.
    page_results: List[dict] = Field(default_factory=list)
    site_coverage: Dict[str, int] = Field(default_factory=dict)
    cross_page_findings: List[dict] = Field(default_factory=list)

    data_layer_present: bool
    pageview_events_found: int
    custom_events_found: int
    analytics_score: int

    # runtime_tested: show the per-tool table as real results instead of "not tested".
    runtime_available: bool = False
    runtime_tested: bool = False
    runtime_result: Optional[dict] = None

    model_config = ConfigDict(from_attributes=True)


class AuditStatsOut(BaseModel):
    total_audits: int
    seo_issues: int
    critical_issues: int
    overall: int
    breakdown: dict


class JourneyOut(BaseModel):
    """Journey Map results."""

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
        """The shared Journey Map view (see reports.journey_view)."""
        from reports.journey_view import build_journey_view  # local import avoids a cycle

        return build_journey_view({
            "available": self.available, "error": self.error, "scan_id": self.scan_id,
            "consent_state": self.consent_state, "health": self.health, "pages": self.pages,
            "interactions": self.interactions, "forms": self.forms, "downloads": self.downloads,
            "journey_map": self.journey_map, "tracking": self.tracking, "findings": self.findings,
            "limits": self.limits, "started_at": self.started_at, "finished_at": self.finished_at,
        })
