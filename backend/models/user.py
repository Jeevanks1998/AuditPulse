"""
models/user.py

The User model — auth fields plus the profile/preferences fields shown on
settings.html (name, company, aiProvider, notification toggles, theme,
language, default schedule, API key), so api/settings.py can read/write
it directly instead of needing a second table.

Relationships fan out to every other domain model: a user owns audits,
tracked websites, recurring schedules, generated reports, and activity
history events.
"""

from datetime import datetime, timezone
from typing import List, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import Base

if TYPE_CHECKING:
    from models.audit import Audit
    from models.website import Website
    from models.report import Report
    from models.history import History


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(120), default="")
    ai_provider: Mapped[str] = mapped_column(String(60), default="Claude (Anthropic)")
    api_key: Mapped[str] = mapped_column(String(64), unique=True)

    notify_audit_completed: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_critical_issue: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_weekly_summary: Mapped[bool] = mapped_column(Boolean, default=False)

    theme: Mapped[str] = mapped_column(String(20), default="light")
    language: Mapped[str] = mapped_column(String(40), default="English")

    schedule_frequency: Mapped[str] = mapped_column(String(40), default="Weekly")
    schedule_time: Mapped[str] = mapped_column(String(80), default="Mondays, 6:00 AM")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # --------------------------------------------------------------------
    # Relationships
    # --------------------------------------------------------------------
    audits: Mapped[List["Audit"]] = relationship(
        "Audit", back_populates="user", cascade="all, delete-orphan"
    )
    websites: Mapped[List["Website"]] = relationship(
        "Website", back_populates="user", cascade="all, delete-orphan"
    )
    reports: Mapped[List["Report"]] = relationship(
        "Report", back_populates="user", cascade="all, delete-orphan"
    )
    activity_events: Mapped[List["History"]] = relationship(
        "History",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="History.created_at.desc()",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<User id={self.id} email={self.email!r}>"
