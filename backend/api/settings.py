"""
The signed-in user's profile and preferences (settings.html): name, company,
notifications, theme, language, default schedule, API key and data export.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import User, generate_api_key, get_current_user
from config.database import get_db
from config.permissions import require_module
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
    # No `email`: it's the sign-in identity the Access Portal uses to find the user.
    # Changing it would dodge an access revoke, so only the portal changes it.
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = Field(default=None, max_length=120)
    company: Optional[str] = Field(default=None, max_length=120)
    ai_provider: Optional[str] = Field(default=None, max_length=60)
    notify_audit_completed: Optional[bool] = None
    notify_critical_issue: Optional[bool] = None
    notify_weekly_summary: Optional[bool] = None
    theme: Optional[str] = Field(default=None, pattern="^(light|dark|system)$")
    language: Optional[str] = Field(default=None, max_length=40)
    schedule_frequency: Optional[str] = Field(default=None, max_length=40)
    schedule_time: Optional[str] = Field(default=None, max_length=80)


class ApiKeyOut(BaseModel):
    api_key: str


class ExportOut(BaseModel):
    exported_at: str
    settings: SettingsOut
    audits: List[AuditOut]


@router.get("/", response_model=SettingsOut)
async def get_settings(current_user: User = Depends(get_current_user)):
    # Reading your own settings needs no permission (every page loads it for the
    # theme). Changing settings, the API key or exports needs the "settings" permission.
    return current_user


@router.patch("/", response_model=SettingsOut)
async def update_settings(
    payload: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("settings")),
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
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_module("settings"))
):
    current_user.api_key = generate_api_key()
    await log_event(db, current_user.id, HistoryEventType.API_KEY_REGENERATED, description="Regenerated API key")
    await db.commit()
    return ApiKeyOut(api_key=current_user.api_key)


@router.get("/export", response_model=ExportOut)
async def export_settings(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_module("settings"))
):
    audits = await get_all_audits(db, current_user)
    return ExportOut(
        exported_at=datetime.now(timezone.utc).isoformat(),
        settings=SettingsOut.model_validate(current_user),
        audits=audits,
    )
