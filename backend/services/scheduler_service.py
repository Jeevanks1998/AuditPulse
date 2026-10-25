"""
Recurring audit schedules: create, edit, delete and run now. The Schedule
model lives here because only this service reads and writes it.
Timed runs are started by scheduler/jobs.py.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base
from models.audit import Audit
from models.history import HistoryEventType, log_event
from models.user import User
from models.website import get_or_create_website
from services import audit_service

FREQUENCY_DAYS = {"Daily": 1, "Weekly": 7, "Monthly": 30, "Yearly": 365}
DEFAULT_RUN_NOW_MAX_PAGES = 50


# Model
class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    website_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("websites.id", ondelete="SET NULL"), nullable=True, index=True
    )

    url: Mapped[str] = mapped_column(String(500))
    frequency: Mapped[str] = mapped_column(String(20), default="Weekly")  # Daily|Weekly|Monthly|Yearly
    time_label: Mapped[str] = mapped_column(String(80), default="Mondays, 6:00 AM")
    depth: Mapped[str] = mapped_column(String(20), default="homepage")
    modules: Mapped[list] = mapped_column(JSON, default=list)

    # Recurrence details, e.g. {"time": "09:00 AM", "timezone": "Asia/Kolkata", "weekday": "Monday"}. Varies by frequency.
    schedule: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)

    # When the schedule is active (start_date, end_date, never_expires).
    schedule_period: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)

    # Automatic email after each run: {"enabled", "to", "cc", "attachments",
    # "subject", "message"} plus the last result (see services/scheduled_email.py).
    email_delivery: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=None)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


# Helpers
def compute_next_run(frequency: str, from_time: Optional[datetime] = None) -> datetime:
    base = from_time or datetime.now(timezone.utc)
    return base + timedelta(days=FREQUENCY_DAYS.get(frequency, 7))


_DELIVERY_STATE_KEYS = ("last_status", "last_sent_at", "last_error", "last_audit_id")


def _delivery_config(delivery, previous: Optional[dict] = None) -> Optional[dict]:
    """Cleans up the dialog's email settings, keeping the last delivery result."""
    if delivery is None:
        return None
    data = delivery.model_dump() if hasattr(delivery, "model_dump") else dict(delivery)
    data["to"] = [str(a) for a in data.get("to") or []]
    data["cc"] = [str(a) for a in data.get("cc") or []]
    for key in _DELIVERY_STATE_KEYS:
        data.pop(key, None)
        if previous and previous.get(key) is not None:
            data[key] = previous[key]
    return data


async def get_owned_schedule(schedule_id: int, db: AsyncSession, user: User) -> Schedule:
    schedule = await db.get(Schedule, schedule_id)
    if not schedule or schedule.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return schedule


# Create / edit / delete / run now
async def list_schedules(db: AsyncSession, user: User) -> List[Schedule]:
    result = await db.execute(
        select(Schedule).where(Schedule.user_id == user.id).order_by(Schedule.created_at.desc())
    )
    return list(result.scalars().all())


async def create_schedule(db: AsyncSession, user: User, payload) -> Schedule:
    website = await get_or_create_website(db, user.id, payload.url)

    schedule = Schedule(
        user_id=user.id,
        website_id=website.id,
        url=payload.url,
        frequency=payload.frequency,
        time_label=payload.time_label,
        depth=payload.depth,
        modules=payload.modules,
        schedule=payload.schedule,
        schedule_period=payload.schedule_period,
        email_delivery=_delivery_config(payload.email_delivery),
        next_run_at=compute_next_run(payload.frequency),
    )
    db.add(schedule)
    await db.flush()

    await log_event(
        db,
        user.id,
        HistoryEventType.SCHEDULE_CREATED,
        description=f"Created a {payload.frequency.lower()} schedule for {payload.url}",
    )

    await db.commit()
    await db.refresh(schedule)
    return schedule


async def update_schedule(schedule_id: int, db: AsyncSession, user: User, payload) -> Schedule:
    schedule = await get_owned_schedule(schedule_id, db, user)
    updates = payload.model_dump(exclude_unset=True)
    if "email_delivery" in updates:
        updates["email_delivery"] = _delivery_config(
            payload.email_delivery, previous=schedule.email_delivery
        )
    for field, value in updates.items():
        setattr(schedule, field, value)
    if "frequency" in updates:
        schedule.next_run_at = compute_next_run(schedule.frequency, schedule.last_run_at)

    await log_event(
        db, user.id, HistoryEventType.SCHEDULE_UPDATED, description=f"Updated schedule for {schedule.url}"
    )

    await db.commit()
    await db.refresh(schedule)
    return schedule


async def delete_schedule(schedule_id: int, db: AsyncSession, user: User) -> None:
    schedule = await get_owned_schedule(schedule_id, db, user)
    await log_event(
        db, user.id, HistoryEventType.SCHEDULE_DELETED, description=f"Deleted schedule for {schedule.url}"
    )
    await db.delete(schedule)
    await db.commit()


async def run_schedule_now(schedule_id: int, db: AsyncSession, user: User) -> Audit:
    """Starts a schedule's audit now. The caller starts the background pipeline."""
    schedule = await get_owned_schedule(schedule_id, db, user)

    audit = audit_service.new_audit(
        user.id,
        schedule.website_id,
        schedule.url,
        schedule.depth,
        DEFAULT_RUN_NOW_MAX_PAGES,
        schedule.modules,
    )
    audit.schedule_id = schedule.id
    db.add(audit)

    schedule.last_run_at = datetime.now(timezone.utc)
    schedule.next_run_at = compute_next_run(schedule.frequency, schedule.last_run_at)

    await db.flush()
    await log_event(
        db,
        user.id,
        HistoryEventType.SCHEDULE_RUN,
        description=f"Ran schedule for {schedule.url} on demand",
        audit_id=audit.id,
    )

    await db.commit()
    await db.refresh(audit)
    return audit
