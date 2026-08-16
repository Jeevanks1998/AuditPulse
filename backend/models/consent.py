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

    gdpr_compliant: Mapped[bool] = mapped_column(Boolean, default=False)
    ccpa_compliant: Mapped[bool] = mapped_column(Boolean, default=False)

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
