"""
api/scheduler.py

Recurring audit schedules. settings.html's "Weekly / Mondays, 6:00 AM"
fields are a user's *default* cadence (see api/settings.py); this module
lets a user manage one or more explicit recurring jobs per URL, and
trigger any of them immediately.

The Schedule model plus all CRUD/run-now logic live in
services.scheduler_service — this file only defines the request/response
schemas (kept local since nothing outside this router needs them) and
wires up routes.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import User
from config.database import get_db
from config.permissions import require_module
from schemas.audit import AuditOut
from services import audit_service, scheduler_service

router = APIRouter()

# Phase 4: Reviewer and Viewer don't have the "scheduler" module at all
# (config/permissions.py), so every route below — including the plain
# list — requires it via require_module("scheduler") in place of the
# plain get_current_user dependency. Unlike audits/settings, there's no
# partial access here: a role either sees schedules or it doesn't.


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class ScheduleCreate(BaseModel):
    url: str
    frequency: str = Field(default="Weekly", pattern="^(Daily|Weekly|Monthly|Yearly)$")
    time_label: str = "Mondays, 6:00 AM"
    depth: str = Field(default="homepage", pattern="^(homepage|full)$")
    modules: List[str] = Field(default_factory=list)
    # Per-frequency recurrence detail (time/timezone/weekday/month_day/...)
    # and the schedule's active window (start_date/end_date/never_expires).
    # Both are free-form dicts — see scheduler_service.Schedule for why.
    schedule: Optional[dict] = None
    schedule_period: Optional[dict] = None


class ScheduleUpdate(BaseModel):
    frequency: Optional[str] = Field(default=None, pattern="^(Daily|Weekly|Monthly|Yearly)$")
    time_label: Optional[str] = None
    depth: Optional[str] = Field(default=None, pattern="^(homepage|full)$")
    modules: Optional[List[str]] = None
    is_active: Optional[bool] = None
    schedule: Optional[dict] = None
    schedule_period: Optional[dict] = None


class ScheduleOut(BaseModel):
    id: int
    url: str
    frequency: str
    time_label: str
    depth: str
    modules: List[str]
    schedule: Optional[dict] = None
    schedule_period: Optional[dict] = None
    is_active: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@router.get("/", response_model=List[ScheduleOut])
async def list_schedules(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_module("scheduler"))
):
    return await scheduler_service.list_schedules(db, current_user)


@router.post("/", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: ScheduleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("scheduler")),
):
    return await scheduler_service.create_schedule(db, current_user, payload)


@router.get("/{schedule_id}", response_model=ScheduleOut)
async def get_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("scheduler")),
):
    return await scheduler_service.get_owned_schedule(schedule_id, db, current_user)


@router.patch("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: int,
    payload: ScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("scheduler")),
):
    return await scheduler_service.update_schedule(schedule_id, db, current_user, payload)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("scheduler")),
):
    await scheduler_service.delete_schedule(schedule_id, db, current_user)


@router.post("/{schedule_id}/run-now", response_model=AuditOut, status_code=status.HTTP_202_ACCEPTED)
async def run_schedule_now(
    schedule_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("scheduler")),
):
    audit = await scheduler_service.run_schedule_now(schedule_id, db, current_user)
    background_tasks.add_task(audit_service.run_audit_pipeline, audit.id)
    return audit
