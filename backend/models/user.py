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
from typing import Dict, List, TYPE_CHECKING

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

    # Set by the AuditPulse Access Portal (see api/access_management.py).
    # Accounts created directly here (register/login-email, before the
    # portal ever syncs them) default to "Viewer" — the least-privileged
    # of the portal's four fixed roles — rather than an empty string, so
    # any future role-gated UI has a safe default to check against.
    role: Mapped[str] = mapped_column(String(40), default="Viewer")

    # Phase 5 of the Access Portal integration (see api/access_management.py).
    # Deliberately a *second* column, separate from is_active below, even
    # though today the portal is the only writer of both:
    #   - is_active           general account status ("Active" in the
    #                         portal's own user list) — also used as the
    #                         API-key auth on/off switch (middleware/auth.py).
    #   - auditpulse_access   whether this specific person's role/assignment
    #                         grants them AuditPulse itself, independent of
    #                         whether their portal account overall is active.
    #                         A user can be Active in the portal but have
    #                         AuditPulse Access: No (e.g. licensed for other
    #                         portal-managed apps only) — login must reject
    #                         that case with a distinct message from an
    #                         inactive account. See api/auth.py's login().
    auditpulse_access: Mapped[bool] = mapped_column(Boolean, default=True)

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

    # --------------------------------------------------------------------
    # Computed, not stored
    # --------------------------------------------------------------------
    @property
    def permissions(self) -> Dict[str, bool]:
        """Module access map for this user's current role.

        Derived from config/permissions.py's MODULE_PERMISSIONS on every
        read rather than stored, so a role change from the Access Portal
        (which only ever writes `role`) takes effect immediately without a
        separate sync step. Exposed on schemas.user.UserOut so the
        frontend (assets/js/permissions.js) can read `user.permissions`
        straight off the logged-in session instead of keeping its own copy
        of the role matrix as the only source of truth.
        """
        from config.permissions import get_permissions  # local import: config/permissions.py's

        # require_module() already imports this module lazily for the same
        # reason (see its docstring) — keeps the import graph one-way
        # instead of a models <-> config cycle at process start-up.
        return get_permissions(self.role)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<User id={self.id} email={self.email!r}>"
