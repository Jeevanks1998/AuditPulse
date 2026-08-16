"""
services/scheduler_service.py

Recurring audit schedules. settings.html's "Weekly / Mondays, 6:00 AM"
fields are a user's *default* cadence (see api/settings.py); this module
lets a user manage one or more explicit recurring jobs per URL, and
trigger any of them immediately.

The Schedule model lives here rather than in models/ — it's config for
*when* an audit runs, not audit result data, so it wasn't part of the
models/ package (audit, report, website, user, issue, consent, analytics,
history), and living next to the service that owns its only read/write
path avoids api/ <-> services/ import cycles. It still shares the same
`Base` and links out to `models.website.Website` / `models.audit.Audit`
like everything else, so table creation in config.database.init_db()
picks it up regardless.

Note: this only provides the CRUD + manual trigger. Actual periodic
execution belongs in a Celery beat worker (CELERY_BROKER_URL /
CELERY_RESULT_BACKEND are already in config.settings) that periodically
queries for schedules whose `next_run_at` has passed and calls
`services.audit_service.run_audit_pipeline` for each — that worker isn't
implemented here.
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

FREQUENCY_DAYS = {"Daily": 1, "Weekly": 7, "Monthly": 30}
DEFAULT_RUN_NOW_MAX_PAGES = 50


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    website_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("websites.id", ondelete="SET NULL"), nullable=True, index=True
    )

    url: Mapped[str] = mapped_column(String(500))
    frequency: Mapped[str] = mapped_column(String(20), default="Weekly")  # Daily|Weekly|Monthly
    time_label: Mapped[str] = mapped_column(String(80), default="Mondays, 6:00 AM")
    depth: Mapped[str] = mapped_column(String(20), default="homepage")
    modules: Mapped[list] = mapped_column(JSON, default=list)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def compute_next_run(frequency: str, from_time: Optional[datetime] = None) -> datetime:
    base = from_time or datetime.now(timezone.utc)
    return base + timedelta(days=FREQUENCY_DAYS.get(frequency, 7))


async def get_owned_schedule(schedule_id: int, db: AsyncSession, user: User) -> Schedule:
    schedule = await db.get(Schedule, schedule_id)
    if not schedule or schedule.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return schedule


# --------------------------------------------------------------------------
# CRUD + manual trigger
# --------------------------------------------------------------------------
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
    """
    Fires a schedule's audit immediately, independent of `next_run_at`.
    Persists the new Audit + bumps the schedule's last/next run, but does
    not start the background pipeline — the caller (api/scheduler.py)
    owns BackgroundTasks and should call `audit_service.run_audit_pipeline`
    with the returned audit's id.
    """
    schedule = await get_owned_schedule(schedule_id, db, user)

    audit = audit_service.new_audit(
        user.id,
        schedule.website_id,
        schedule.url,
        schedule.depth,
        DEFAULT_RUN_NOW_MAX_PAGES,
        schedule.modules,
    )
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
