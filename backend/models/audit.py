"""
models/audit.py

The Audit model — one row per audit run (queued -> running -> completed
/ failed). Carries the lightweight JSON `breakdown` / `findings` columns
that the dashboard and report views read for fast, denormalized access,
plus relationships out to the normalized detail tables: Issue (one row
per finding), Consent / Analytics (one-to-one module results), and
Report (share/export metadata).

Business logic (the pipeline, stats aggregation, query helpers) stays in
api/audit.py — this module only defines the schema and stays free of
route/session concerns so other models can import it without pulling in
FastAPI.
"""

from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.constants import DEFAULT_MAX_PAGES
from config.database import Base

if TYPE_CHECKING:
    from models.user import User
    from models.website import Website
    from models.issue import Issue
    from models.consent import Consent
    from models.analytics import Analytics
    from models.report import Report
    from models.report_email import ReportEmail


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    website_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("websites.id", ondelete="SET NULL"), nullable=True, index=True
    )

    url: Mapped[str] = mapped_column(String(500))
    label: Mapped[str] = mapped_column(String(40), default="Homepage")  # "Homepage" | "Full site"
    depth: Mapped[str] = mapped_column(String(20), default="homepage")  # "homepage" | "full"
    max_pages: Mapped[int] = mapped_column(Integer, default=DEFAULT_MAX_PAGES)
    modules: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|completed|failed
    current_step: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    percent: Mapped[int] = mapped_column(Integer, default=0)

    overall_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    breakdown: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # seo/performance/accessibility/security/ux/images/links/mobile/forms
    findings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)   # [{module, severity, title, description}]

    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------
    user: Mapped["User"] = relationship("User", back_populates="audits")
    website: Mapped[Optional["Website"]] = relationship("Website", back_populates="audits")

    issues: Mapped[List["Issue"]] = relationship(
        "Issue",
        back_populates="audit",
        cascade="all, delete-orphan",
        order_by="Issue.created_at",
    )
    consent_result: Mapped[Optional["Consent"]] = relationship(
        "Consent", back_populates="audit", uselist=False, cascade="all, delete-orphan"
    )
    analytics_result: Mapped[Optional["Analytics"]] = relationship(
        "Analytics", back_populates="audit", uselist=False, cascade="all, delete-orphan"
    )
    report: Mapped[Optional["Report"]] = relationship(
        "Report", back_populates="audit", uselist=False, cascade="all, delete-orphan"
    )
    report_emails: Mapped[List["ReportEmail"]] = relationship(
        "ReportEmail",
        back_populates="audit",
        cascade="all, delete-orphan",
        order_by="ReportEmail.sent_at.desc()",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Audit id={self.id} url={self.url!r} status={self.status!r}>"
