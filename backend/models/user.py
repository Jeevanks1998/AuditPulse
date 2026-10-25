"""
A user: sign-in fields, profile and preferences (settings page), role and access from the Access Portal.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, TYPE_CHECKING

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
    # Old password column, no longer used (sign-in is Google Authenticator). Kept so old rows still load.
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    company: Mapped[str] = mapped_column(String(120), default="")
    ai_provider: Mapped[str] = mapped_column(String(60), default="Claude (Anthropic)")
    api_key: Mapped[str] = mapped_column(String(64), unique=True)

    # Role from the Access Portal. Defaults to "Viewer" (least access).
    role: Mapped[str] = mapped_column(String(40), default="Viewer")

    # Two separate flags, both set by the Access Portal:
    #   is_active         - the account is active (also turns API-key access on/off)
    #   auditpulse_access - this person may use AuditPulse
    # Someone can be active in the portal without AuditPulse access; login shows a
    # different message for each case.
    auditpulse_access: Mapped[bool] = mapped_column(Boolean, default=True)

    notify_audit_completed: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_critical_issue: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_weekly_summary: Mapped[bool] = mapped_column(Boolean, default=False)

    theme: Mapped[str] = mapped_column(String(20), default="light")
    language: Mapped[str] = mapped_column(String(40), default="English")

    schedule_frequency: Mapped[str] = mapped_column(String(40), default="Weekly")
    schedule_time: Mapped[str] = mapped_column(String(80), default="Mondays, 6:00 AM")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Google Authenticator sign-in:
    #   new user:                mfa_enabled False, auth_setup_required True
    #   after first set-up:      mfa_enabled True,  auth_setup_required False
    #   admin reset in portal:   back to the new-user state, secret cleared
    mfa_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auth_setup_required: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
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

    # Computed, not stored
    @property
    def permissions(self) -> Dict[str, bool]:
        """Module access for this user's role, worked out on each read so role changes apply at once."""
        from config.permissions import get_permissions  # local import

        # Imported inside the function to avoid a models <-> config import cycle.
        return get_permissions(self.role)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<User id={self.id} email={self.email!r}>"
