"""
models/consent.py

Result of the "consent" audit module (see config.constants.AUDIT_MODULES
and the consent checkbox on audit.html) — cookie banner / privacy-policy
/ GDPR-CCPA compliance signals for the audited site. One row per audit,
one-to-one with Audit.
"""

from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import Base

if TYPE_CHECKING:
    from models.audit import Audit


class Consent(Base):
    __tablename__ = "consent_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(
        ForeignKey("audits.id", ondelete="CASCADE"), unique=True, index=True
    )

    has_cookie_banner: Mapped[bool] = mapped_column(Boolean, default=False)
    banner_blocks_scripts_pre_consent: Mapped[bool] = mapped_column(Boolean, default=False)

    # ------------------------------------------------------------------
    # Region detection (consent.region_detector.detect_region), stored
    # verbatim so the history page can show *why* a given audit was (or
    # wasn't) judged against a framework without re-running detection.
    # ------------------------------------------------------------------
    # REGION_* bucket (consent.consent_score.REGION_EU/UK/US_CALIFORNIA/
    # UNKNOWN/...) — the coarse region resolve_applicable_frameworks
    # actually keys off. "UNKNOWN" default matches
    # consent.consent_score.REGION_UNKNOWN for audits with no region
    # signals (or where the consent module didn't run).
    detected_region: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    # Human-readable, more specific than detected_region — e.g. "France",
    # "California", "Germany", or "Unknown" — RegionDetectionResult
    # .region_label. Two sites can share detected_region="EU" but show
    # different countries here.
    detected_country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Display name of whichever single regional framework this audit was
    # actually judged against — "GDPR" / "UK GDPR" / "Swiss FADP" /
    # "CCPA/CPRA" — or None when detected_region isn't in scope for any
    # of them (RegionDetectionResult.framework /
    # ApplicableFrameworks.gdpr_framework_name). At most one framework
    # ever applies per audit, so this single column (rather than a
    # separate flag per framework) is enough to know which applied.
    compliance_framework: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # "high" | "medium" | "low" | "none" — RegionDetectionResult
    # .confidence. "none" means no region signal was found at all
    # (distinct from a low-confidence guess); the history page should
    # flag "none"/"low" rows as worth a manual look rather than trusting
    # the auto-detected region outright.
    region_confidence: Mapped[str] = mapped_column(String(10), default="none")
    # Which signal(s) won — e.g. "Domain + hreflang", "Country/language
    # selector" — RegionDetectionResult.source. "None" when no signal
    # fired.
    region_detection_source: Mapped[str] = mapped_column(String(200), default="None")
    # The synthesized human-readable explanation behind the detected
    # region — RegionDetectionResult.reason — e.g. "Domain uses the .fr
    # country-code TLD, associated with France." Shown as a tooltip/
    # detail row on the history page rather than making someone dig into
    # the raw signals list.
    region_detection_reason: Mapped[str] = mapped_column(String(1000), default="")

    # Whether a GDPR-family framework (GDPR / UK GDPR / Swiss FADP) or
    # CCPA/CPRA respectively actually applied to this audit at all —
    # consent.consent_score.GdprAssessment.applicable /
    # CcpaAssessment.applicable. Check these before treating
    # gdpr_compliant/ccpa_compliant as a real verdict: both those columns
    # are non-nullable booleans today and default to False, which is
    # indistinguishable from a real "non-compliant" without this flag —
    # False here means "not assessed", not "failed".
    gdpr_assessed: Mapped[bool] = mapped_column(Boolean, default=False)
    ccpa_assessed: Mapped[bool] = mapped_column(Boolean, default=False)

    gdpr_compliant: Mapped[bool] = mapped_column(Boolean, default=False)
    # Per-check breakdown behind gdpr_compliant above: one entry per key in
    # consent.consent_score.GDPR_CHECK_ORDER, each True/False/None ("not
    # evaluated"). gdpr_compliant is just consent.consent_score.GdprAssessment
    # .compliant computed from this dict at write time — this is the field a
    # report should actually render instead of the single boolean.
    gdpr_checks: Mapped[dict] = mapped_column(JSON, default=dict)
    # Structured evidence backing whichever gdpr_checks entries have it (see
    # consent.consent_score.GdprCheck.evidence) — sparse, keyed the same as
    # gdpr_checks. Currently only trackers_blocked_pre_consent populates
    # this, with the actual tracker request count/names from consent's live
    # pre-consent network capture.
    gdpr_check_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    ccpa_compliant: Mapped[bool] = mapped_column(Boolean, default=False)
    # Per-check breakdown behind ccpa_compliant above: one entry per key in
    # consent.consent_score.CCPA_CHECK_ORDER, each True/False/None ("not
    # evaluated"). ccpa_compliant is just consent.consent_score.CcpaAssessment
    # .compliant computed from this dict at write time — same relationship
    # gdpr_checks above has to gdpr_compliant.
    ccpa_checks: Mapped[dict] = mapped_column(JSON, default=dict)

    privacy_policy_found: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_policy_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    cookies_detected: Mapped[list] = mapped_column(JSON, default=list)          # [{name, category, domain, expires}]
    third_party_trackers: Mapped[list] = mapped_column(JSON, default=list)      # ["Google Analytics", "Meta Pixel", ...]

    consent_score: Mapped[int] = mapped_column(Integer, default=0)

    # Path (relative to SCREENSHOT_DIR, e.g. "screenshots/example_com_banner.png")
    # written by consent.screenshots.capture_banner_screenshot. None when
    # Playwright isn't installed, capture was skipped, or the capture failed.
    banner_screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # The remaining three evidence screenshots from consent.runtime's
    # click-through pass (Personalize/Manage Preferences, after Reject,
    # after Accept) — each in its own clean browser context. None when the
    # runtime pass didn't run, wasn't available, or that particular leg
    # didn't find a matching button to click.
    preferences_screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    reject_screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    accept_screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Whether consent.runtime.run_consent_runtime ran at all (browser
    # launched, page loaded) vs. actually got as far as clicking
    # Accept/Reject — see consent.consent_score.build_consent_summary for
    # the exact distinction. runtime_result is the full serialized
    # ConsentRuntimeResult (before/after cookies+network, click verdicts),
    # kept for the evidence-package export.
    runtime_available: Mapped[bool] = mapped_column(Boolean, default=False)
    runtime_tested: Mapped[bool] = mapped_column(Boolean, default=False)
    runtime_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------
    audit: Mapped["Audit"] = relationship("Audit", back_populates="consent_result")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Consent audit_id={self.audit_id} score={self.consent_score}>"
