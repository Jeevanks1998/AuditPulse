"""
Consent results for one audit: banner, cookies, GDPR/CCPA checks, region and evidence.
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

    gdpr_compliant: Mapped[bool] = mapped_column(Boolean, default=False)
    # GDPR check -> True / False / None (not tested). gdpr_compliant comes from these.
    gdpr_checks: Mapped[dict] = mapped_column(JSON, default=dict)
    # Evidence for the GDPR checks that have it.
    gdpr_check_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    ccpa_compliant: Mapped[bool] = mapped_column(Boolean, default=False)
    # CCPA check -> True / False / None (not tested).
    ccpa_checks: Mapped[dict] = mapped_column(JSON, default=dict)

    # Region and which laws were assessed. A law that doesn't apply is "not_assessed", not failed.
    applicability: Mapped[dict] = mapped_column(JSON, default=dict)
    # Law-neutral scan: rendered banner, buttons, checks and evidence.
    technical_scan: Mapped[dict] = mapped_column(JSON, default=dict)

    # Detected region and the banner's buttons.
    detected_region: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    region_confidence: Mapped[str] = mapped_column(String(16), default="low")
    region_evidence: Mapped[list] = mapped_column(JSON, default=list)
    applicable_frameworks: Mapped[list] = mapped_column(JSON, default=list)
    applicability_status: Mapped[str] = mapped_column(String(32), default="not_determined")
    consent_controls: Mapped[list] = mapped_column(JSON, default=list)

    privacy_policy_found: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_policy_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    cookies_detected: Mapped[list] = mapped_column(JSON, default=list)          # [{name, category, domain, expires}]
    third_party_trackers: Mapped[list] = mapped_column(JSON, default=list)      # ["Google Analytics", "Meta Pixel", ...]

    consent_score: Mapped[int] = mapped_column(Integer, default=0)

    # Banner screenshot path. None if no screenshot was taken.
    banner_screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Settings, after-Reject and after-Accept screenshots. None if that test didn't run.
    preferences_screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    reject_screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    accept_screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # runtime_available: the browser check ran. runtime_tested: it clicked Accept/Reject. runtime_result: full result, for exports.
    runtime_available: Mapped[bool] = mapped_column(Boolean, default=False)
    runtime_tested: Mapped[bool] = mapped_column(Boolean, default=False)
    runtime_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    audit: Mapped["Audit"] = relationship("Audit", back_populates="consent_result")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Consent audit_id={self.audit_id} score={self.consent_score}>"
