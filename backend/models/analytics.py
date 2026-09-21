"""
models/analytics.py

Result of the "analytics" audit module — which trackers/tag managers the
site loads (GA4, GTM, Meta Pixel, etc.), whether a dataLayer is present,
and how many tracked events were detected during the crawl. One row per
audit, one-to-one with Audit.
"""

from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import Base

if TYPE_CHECKING:
    from models.audit import Audit


class Analytics(Base):
    __tablename__ = "analytics_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(
        ForeignKey("audits.id", ondelete="CASCADE"), unique=True, index=True
    )

    trackers_detected: Mapped[list] = mapped_column(JSON, default=list)  # ["Google Analytics 4", "Meta Pixel", ...]

    tag_manager_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    gtm_container_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    ga_measurement_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # Every detected vendor's actual configuration ({vendor_key: [ids]}) —
    # Adobe report suites, Piano site IDs, Clarity project IDs, Hotjar
    # site IDs, Meta Pixel IDs, LinkedIn partner IDs, TikTok Pixel IDs,
    # plus GA4/GTM's full ID lists (gtm_container_id/ga_measurement_id
    # above stay as the first-detected value for backward compatibility
    # with any existing consumer expecting a single string). Only
    # vendors analytics.analytics_score.build_analytics_summary actually
    # detected are present as keys — never a placeholder entry for an
    # undetected vendor. See analytics.analytics_score.VENDOR_ID_ATTR.
    vendor_configs: Mapped[dict] = mapped_column(JSON, default=dict)

    data_layer_present: Mapped[bool] = mapped_column(Boolean, default=False)
    pageview_events_found: Mapped[int] = mapped_column(Integer, default=0)
    custom_events_found: Mapped[int] = mapped_column(Integer, default=0)

    analytics_score: Mapped[int] = mapped_column(Integer, default=0)

    # Whether analytics.runtime.run_analytics_runtime ran at all
    # (browser launched, page loaded) vs. actually captured live
    # vendor requests — see analytics.analytics_score.build_analytics_summary.
    # runtime_result is the full serialized AnalyticsRuntimeResult
    # (per-vendor Page View/Scroll/Click verdicts), kept for the
    # evidence-package export.
    runtime_available: Mapped[bool] = mapped_column(Boolean, default=False)
    runtime_tested: Mapped[bool] = mapped_column(Boolean, default=False)
    runtime_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # ----------------------------------------------------------------
    # Phase 2 — full-site analytics. Populated only when the audit's
    # depth is "full"; a homepage-only audit leaves these at their
    # defaults (empty list / dict), which the frontend reads as "no
    # full-site data" rather than as zero pages having analytics.
    # page_results: one entry per crawled page (serialized
    # analytics.analytics_score.PageAnalyticsResult) — url, detected
    # trackers, vendor_configs, page score, page findings.
    # site_coverage: analytics.analytics_score.compute_site_coverage's
    # output (pages_scanned, pages_with_analytics, ...).
    # cross_page_findings: analytics.analytics_score.check_cross_page_consistency's
    # output — kept separate from the page-level findings folded into
    # Audit.findings so the report can render its own "cross-page
    # consistency" section without re-filtering the full findings list.
    page_results: Mapped[list] = mapped_column(JSON, default=list)
    site_coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    cross_page_findings: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------
    audit: Mapped["Audit"] = relationship("Audit", back_populates="analytics_result")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Analytics audit_id={self.audit_id} score={self.analytics_score}>"
