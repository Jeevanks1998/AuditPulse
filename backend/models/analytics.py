"""
Analytics results for one audit: tools found, dataLayer, events and the live check.
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

    # IDs per detected tool ({"ga4": [...]}). Only detected tools appear.
    vendor_configs: Mapped[dict] = mapped_column(JSON, default=dict)

    data_layer_present: Mapped[bool] = mapped_column(Boolean, default=False)
    pageview_events_found: Mapped[int] = mapped_column(Integer, default=0)
    custom_events_found: Mapped[int] = mapped_column(Integer, default=0)

    analytics_score: Mapped[int] = mapped_column(Integer, default=0)

    # runtime_available: the live check ran. runtime_tested: it captured real requests. runtime_result: full result, for exports.
    runtime_available: Mapped[bool] = mapped_column(Boolean, default=False)
    runtime_tested: Mapped[bool] = mapped_column(Boolean, default=False)
    runtime_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Full-site results (empty for homepage audits): page_results (one per page),
    # site_coverage (counts) and cross_page_findings.
    page_results: Mapped[list] = mapped_column(JSON, default=list)
    site_coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    cross_page_findings: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    audit: Mapped["Audit"] = relationship("Audit", back_populates="analytics_result")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Analytics audit_id={self.audit_id} score={self.analytics_score}>"
