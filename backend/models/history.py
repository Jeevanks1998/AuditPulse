"""
models/history.py

History is a lightweight, append-only activity log — one row per
notable account event (login, audit started/completed/failed, settings
changed, schedule created/run, report shared, etc.). It's distinct from
the "audit history" list on history.html (that's just a paginated view
over Audit, served by api/history.py): History powers a broader
account-activity feed and gives every other module a single, cheap way
to record "something happened" without designing a bespoke table for it.

`log_event` is the one helper every router should call to write an
entry; keeping it here (rather than duplicating `db.add(History(...))`
everywhere) keeps the event_type vocabulary consistent.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import Base

if TYPE_CHECKING:
    from models.user import User


class HistoryEventType(str, Enum):
    LOGIN = "login"
    REGISTER = "register"
    AUDIT_CREATED = "audit_created"
    AUDIT_COMPLETED = "audit_completed"
    AUDIT_FAILED = "audit_failed"
    AUDIT_DELETED = "audit_deleted"
    REPORT_SHARED = "report_shared"
    SCHEDULE_CREATED = "schedule_created"
    SCHEDULE_UPDATED = "schedule_updated"
    SCHEDULE_DELETED = "schedule_deleted"
    SCHEDULE_RUN = "schedule_run"
    SETTINGS_UPDATED = "settings_updated"
    API_KEY_REGENERATED = "api_key_regenerated"


class History(Base):
    __tablename__ = "history_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    audit_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("audits.id", ondelete="SET NULL"), nullable=True, index=True
    )

    event_type: Mapped[str] = mapped_column(String(40), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------
    user: Mapped["User"] = relationship("User", back_populates="activity_events")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<History id={self.id} event_type={self.event_type!r}>"


async def log_event(
    db: AsyncSession,
    user_id: int,
    event_type: "HistoryEventType | str",
    description: str = "",
    audit_id: Optional[int] = None,
    meta: Optional[dict] = None,
) -> History:
    """Append one activity row. Does not commit — caller controls the transaction."""
    entry = History(
        user_id=user_id,
        audit_id=audit_id,
        event_type=event_type.value if isinstance(event_type, HistoryEventType) else event_type,
        description=description,
        meta=meta,
    )
    db.add(entry)
    return entry
