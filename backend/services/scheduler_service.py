"""
Recurring audit schedules: create, edit, delete and run now. The Schedule
model lives here because only this service reads and writes it.
Timed runs are started by scheduler/jobs.py.
"""

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


# Next run time
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def _get(cfg: dict, *keys, default=None):
    """Reads a key in snake_case or camelCase (the page sends camelCase, the API stores snake_case)."""
    for k in keys:
        if cfg.get(k) not in (None, ""):
            return cfg[k]
    return default


def _zone(name) -> ZoneInfo:
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo("UTC")


def _parse_time(text) -> tuple:
    """'09:00 AM', '9:30 pm', '21:15' -> (hour, minute). Defaults to 09:00."""
    m = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([AaPp][Mm])?\s*$", str(text or ""))
    if not m:
        return 9, 0
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return 9, 0
    return hour, minute


def _date(text) -> Optional[date]:
    try:
        return date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        return None


def _candidates(frequency: str, cfg: dict, start: date):
    """Run dates from `start` onwards, in order."""
    if frequency == "Daily":
        for i in range(0, 400):
            yield start + timedelta(days=i)
    elif frequency == "Monthly":
        last_day = str(_get(cfg, "month_day_mode", "monthDayMode", default="specific")) == "last"
        want = int(_get(cfg, "month_day", "monthDay", default=15))
        y, m = start.year, start.month
        for _ in range(0, 26):
            days = calendar.monthrange(y, m)[1]
            yield date(y, m, days if last_day else min(max(want, 1), days))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    elif frequency == "Yearly":
        name = str(_get(cfg, "year_month", "yearMonth", default="January"))
        month = MONTHS.index(name) + 1 if name in MONTHS else 1
        want = int(_get(cfg, "year_day", "yearDay", default=1))
        for y in range(start.year, start.year + 3):
            yield date(y, month, min(max(want, 1), calendar.monthrange(y, month)[1]))
    else:  # Weekly
        name = str(_get(cfg, "weekday", default="Monday"))
        wd = WEEKDAYS.index(name) if name in WEEKDAYS else 0
        first = start + timedelta(days=(wd - start.weekday()) % 7)
        for i in range(0, 60):
            yield first + timedelta(weeks=i)


def compute_next_run(frequency: str, from_time: Optional[datetime] = None,
                     schedule: Optional[dict] = None, period: Optional[dict] = None) -> Optional[datetime]:
    """Next run (UTC) strictly after `from_time`, at the chosen time in the chosen time zone.
    Respects the schedule period: not before the start date, and None after the end date
    (unless it never expires)."""
    cfg, per = dict(schedule or {}), dict(period or {})
    tz = _zone(_get(cfg, "timezone", default="UTC"))
    hour, minute = _parse_time(_get(cfg, "time", default="09:00 AM"))
    after = (from_time or datetime.now(timezone.utc)).astimezone(tz)

    start = after.date()
    start_date = _date(_get(per, "start_date", "startDate"))
    if start_date and start_date > start:
        start = start_date
    never = _get(per, "never_expires", "neverExpires", default=True)
    end_date = None if never in (True, "true", 1) else _date(_get(per, "end_date", "endDate"))

    for day in _candidates(frequency, cfg, start):
        run = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        if run <= after:
            continue
        if end_date and day > end_date:
            return None
        return run.astimezone(timezone.utc)
    return None


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
        next_run_at=compute_next_run(payload.frequency, schedule=payload.schedule, period=payload.schedule_period),
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
    if {"frequency", "schedule", "schedule_period"} & updates.keys():
        schedule.next_run_at = compute_next_run(schedule.frequency, schedule=schedule.schedule,
                                                period=schedule.schedule_period)

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
    # "Run now" doesn't move the regular timetable.

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
