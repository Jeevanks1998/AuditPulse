"""
models/report.py

Report is the persisted, shareable artifact generated from a completed
Audit (report.html). It replaces the old ad hoc `Audit.share_token`
column with a proper one-to-one row so share links can expire, track
view counts, and (once wired up) point at an exported PDF on disk —
without bloating the Audit table itself.

api/reports.py builds the on-screen ReportOut payload from Audit +
Issue on the fly (that data changes with the audit); this model only
tracks the *sharing/export* side effects layered on top of it.
"""

from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import Base

if TYPE_CHECKING:
    from models.audit import Audit
    from models.user import User


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(
        ForeignKey("audits.id", ondelete="CASCADE"), unique=True, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    share_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)

    pdf_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------
    audit: Mapped["Audit"] = relationship("Audit", back_populates="report")
    user: Mapped["User"] = relationship("User", back_populates="reports")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Report audit_id={self.audit_id} share_token={self.share_token!r}>"
