"""
api/settings.py

Reads/writes the profile + preferences fields on the User model (see
api/auth.py) that back settings.html — name/email/company/aiProvider,
notification toggles, theme, language, default schedule, and API key
management/export. Mirrors window.Api.settings.* in assets/js/api.js
(get, save, regenerateApiKey, exportJson) and is wired into the
settings.html form via the inline handlers in assets/js/app.js
(initSettingsPage).
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import User, generate_api_key, get_current_user
from config.database import get_db
from models.history import HistoryEventType, log_event
from schemas.audit import AuditOut
from services.audit_service import get_all_audits

router = APIRouter()


class SettingsOut(BaseModel):
    name: str
    email: EmailStr
    company: str
    ai_provider: str
    notify_audit_completed: bool
    notify_critical_issue: bool
    notify_weekly_summary: bool
    theme: str
    language: str
    schedule_frequency: str
    schedule_time: str
    api_key: str

    model_config = ConfigDict(from_attributes=True)


class SettingsUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    company: Optional[str] = None
    ai_provider: Optional[str] = None
    notify_audit_completed: Optional[bool] = None
    notify_critical_issue: Optional[bool] = None
    notify_weekly_summary: Optional[bool] = None
    theme: Optional[str] = None
    language: Optional[str] = None
    schedule_frequency: Optional[str] = None
    schedule_time: Optional[str] = None


class ApiKeyOut(BaseModel):
    api_key: str


class ExportOut(BaseModel):
    exported_at: str
    settings: SettingsOut
    audits: List[AuditOut]


@router.get("/", response_model=SettingsOut)
async def get_settings(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/", response_model=SettingsOut)
async def update_settings(
    payload: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(current_user, field, value)

    if updates:
        await log_event(
            db,
            current_user.id,
            HistoryEventType.SETTINGS_UPDATED,
            description=f"Updated settings: {', '.join(updates.keys())}",
        )

    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/api-key/regenerate", response_model=ApiKeyOut)
async def regenerate_api_key(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    current_user.api_key = generate_api_key()
    await log_event(db, current_user.id, HistoryEventType.API_KEY_REGENERATED, description="Regenerated API key")
    await db.commit()
    return ApiKeyOut(api_key=current_user.api_key)


@router.get("/export", response_model=ExportOut)
async def export_settings(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    audits = await get_all_audits(db, current_user)
    return ExportOut(
        exported_at=datetime.now(timezone.utc).isoformat(),
        settings=SettingsOut.model_validate(current_user),
        audits=audits,
    )
