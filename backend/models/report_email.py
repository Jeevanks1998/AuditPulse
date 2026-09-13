"""
models/report_email.py

Email History (requirements §10): one row per "Send to POC" attempt
(§9.1) — who it went to, what was sent, and whether it succeeded — so
report.html can show a send history alongside the report and so a failed
send can be diagnosed without digging through server logs.

Distinct from models.report.Report (the shareable-link artifact): this
tracks outbound *email* deliveries of that report, which can happen zero,
one, or many times for the same audit.
"""

from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import Base

if TYPE_CHECKING:
    from models.audit import Audit
    from models.user import User


class ReportEmail(Base):
    __tablename__ = "report_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # Stored as JSON lists rather than a single delimited string so a
    # multi-recipient To/CC round-trips exactly as entered in the modal.
    recipient_to: Mapped[list] = mapped_column(JSON, default=list)
    recipient_cc: Mapped[list] = mapped_column(JSON, default=list)

    subject: Mapped[str] = mapped_column(String(255), default="")
    attachments: Mapped[list] = mapped_column(JSON, default=list)  # attachment keys actually sent

    status: Mapped[str] = mapped_column(String(20), default="failed", index=True)  # "sent" | "failed"
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------
    audit: Mapped["Audit"] = relationship("Audit", back_populates="report_emails")
    user: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ReportEmail audit_id={self.audit_id} status={self.status!r}>"
