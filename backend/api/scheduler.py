"""
Recurring audit schedules: create, edit, delete and run now.
Logic lives in services.scheduler_service.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import User
from config.database import get_db
from config.permissions import require_module
from schemas.audit import AuditOut
from emailer.attachments import ATTACHMENT_CHOICES
from services import audit_service, scheduler_service

router = APIRouter()

# Every route needs the "scheduler" permission (Reviewers and Viewers don't have it).


# Schemas
class ScheduleEmailDelivery(BaseModel):
    """Who receives the report after each run, and which attachments (same choices as "Send to POC")."""

    enabled: bool = False
    to: List[EmailStr] = Field(default_factory=list, max_length=25)
    cc: List[EmailStr] = Field(default_factory=list, max_length=25)
    attachments: List[str] = Field(default_factory=lambda: ["pdf"])
    subject: Optional[str] = Field(default=None, max_length=200)
    message: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("attachments")
    @classmethod
    def _known_attachments(cls, v: List[str]) -> List[str]:
        unknown = [k for k in v if k not in ATTACHMENT_CHOICES]
        if unknown:
            raise ValueError(f"Unknown report type(s): {', '.join(unknown)}")
        return list(dict.fromkeys(v)) or ["pdf"]

    @field_validator("to")
    @classmethod
    def _recipients_when_enabled(cls, v, info):
        if info.data.get("enabled") and not v:
            raise ValueError("Add at least one recipient email, or turn off email delivery.")
        return v


class ScheduleEmailDeliveryOut(BaseModel):
    enabled: bool = False
    to: List[str] = Field(default_factory=list)
    cc: List[str] = Field(default_factory=list)
    attachments: List[str] = Field(default_factory=list)
    subject: Optional[str] = None
    message: Optional[str] = None
    last_status: Optional[str] = None  # "sent" | "failed"
    last_sent_at: Optional[str] = None
    last_error: Optional[str] = None
    last_audit_id: Optional[int] = None


class ScheduleCreate(BaseModel):
    url: str = Field(max_length=500)

    @field_validator("url")
    @classmethod
    def _public_url(cls, v: str) -> str:
        # Same rules as a one-off audit: public http(s) sites only.
        from schemas.audit import normalize_audit_url
        return normalize_audit_url(v)
    frequency: str = Field(default="Weekly", pattern="^(Daily|Weekly|Monthly|Yearly)$")
    time_label: str = "Mondays, 6:00 AM"
    depth: str = Field(default="homepage", pattern="^(homepage|full)$")
    modules: List[str] = Field(default_factory=list)
    # Recurrence details (time, timezone, weekday...) and active dates (start, end, never_expires).
    schedule: Optional[dict] = None
    schedule_period: Optional[dict] = None
    email_delivery: Optional[ScheduleEmailDelivery] = None


class ScheduleUpdate(BaseModel):
    frequency: Optional[str] = Field(default=None, pattern="^(Daily|Weekly|Monthly|Yearly)$")
    time_label: Optional[str] = None
    depth: Optional[str] = Field(default=None, pattern="^(homepage|full)$")
    modules: Optional[List[str]] = None
    is_active: Optional[bool] = None
    schedule: Optional[dict] = None
    schedule_period: Optional[dict] = None
    email_delivery: Optional[ScheduleEmailDelivery] = None


class ScheduleOut(BaseModel):
    id: int
    url: str
    frequency: str
    time_label: str
    depth: str
    modules: List[str]
    schedule: Optional[dict] = None
    schedule_period: Optional[dict] = None
    email_delivery: Optional[ScheduleEmailDeliveryOut] = None
    is_active: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Routes
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
