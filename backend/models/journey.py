"""
Journey Map result for one audit, stored as JSON: health, pages, interactions, forms, downloads, map, tracking and findings.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class Journey(Base):
    __tablename__ = "journey_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(
        ForeignKey("audits.id", ondelete="CASCADE"), unique=True, index=True
    )

    available: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    scan_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    consent_state: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    journey_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    health: Mapped[dict] = mapped_column(JSON, default=dict)
    pages: Mapped[list] = mapped_column(JSON, default=list)
    interactions: Mapped[list] = mapped_column(JSON, default=list)
    forms: Mapped[list] = mapped_column(JSON, default=list)
    downloads: Mapped[list] = mapped_column(JSON, default=list)
    journey_map: Mapped[dict] = mapped_column(JSON, default=dict)
    tracking: Mapped[dict] = mapped_column(JSON, default=dict)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    limits: Mapped[dict] = mapped_column(JSON, default=dict)

    started_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    finished_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Journey audit_id={self.audit_id} score={self.journey_score}>"
