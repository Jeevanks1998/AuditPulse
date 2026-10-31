"""
A finding the site's team has reviewed: "accepted" (an intentional, approved
choice, e.g. a vendor approved by the DPO) or "to_verify". Kept per website, so
every later audit of the site applies it too. See services/accepted_findings.py.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class AcceptedFinding(Base):
    __tablename__ = "accepted_findings"
    __table_args__ = (UniqueConstraint("website_id", "fingerprint", name="uq_accepted_findings_site_fp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(400))
    module: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="accepted")  # accepted | to_verify
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
