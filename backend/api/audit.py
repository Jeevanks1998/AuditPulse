"""
Endpoints to start an audit, check progress and get results. Logic lives in services.audit_service.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from api.auth import User, get_current_user
from config.database import get_db
from config.permissions import require_module
from models.analytics import Analytics
from models.audit import Audit
from models.consent import Consent
from models.journey import Journey
from schemas.audit import (
    AnalyticsOut, AuditCreate, AuditOut, AuditProgressOut, AuditStatsOut, ConsentOut, JourneyOut,
)
from services import audit_service

router = APIRouter()


@router.post("/", response_model=AuditOut, status_code=status.HTTP_202_ACCEPTED)
async def start_audit(
    payload: AuditCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    # Starting an audit needs the "audits" permission (Viewers can't); reading is open to all signed-in users.
    current_user: User = Depends(require_module("audits")),
):
    audit = await audit_service.start_audit(db, current_user, payload)
    background_tasks.add_task(audit_service.run_audit_pipeline, audit.id)
    return audit


@router.get("/stats", response_model=AuditStatsOut)
async def audit_stats(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return await audit_service.compute_stats(db, current_user)


@router.get("/recent", response_model=List[AuditOut])
async def recent_audits(
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await audit_service.get_recent_audits(db, current_user, limit=limit)


@router.get("/{audit_id}/progress", response_model=AuditProgressOut)
async def audit_progress(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    audit = await db.get(Audit, audit_id)
    if not audit or audit.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")
    return AuditProgressOut(
        id=audit.id,
        status=audit.status,
        current_step=audit.current_step,
        percent=audit.percent,
        overall_score=audit.overall_score,
    )


@router.get("/{audit_id}/consent", response_model=ConsentOut)
async def audit_consent(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    audit = await db.get(Audit, audit_id)
    if not audit or audit.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")

    result = await db.execute(select(Consent).where(Consent.audit_id == audit_id))
    consent = result.scalar_one_or_none()
    if not consent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No consent scan for this audit — was 'consent' included in its modules?",
        )
    return consent


@router.get("/{audit_id}/analytics", response_model=AnalyticsOut)
async def audit_analytics(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    audit = await db.get(Audit, audit_id)
    if not audit or audit.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")

    result = await db.execute(select(Analytics).where(Analytics.audit_id == audit_id))
    analytics = result.scalar_one_or_none()
    if not analytics:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No analytics scan for this audit — was 'analytics' included in its modules?",
        )
    return analytics


@router.get("/{audit_id}/journey", response_model=JourneyOut)
async def audit_journey(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Journey Map result: pages, interactions, map, tracking checks and findings."""
    audit = await db.get(Audit, audit_id)
    if not audit or audit.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")

    result = await db.execute(select(Journey).where(Journey.audit_id == audit_id))
    journey = result.scalar_one_or_none()
    if not journey:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No journey map scan for this audit — was 'journey' included in its modules?",
        )
    return journey


async def _cookie_inventory(audit_id: int, db: AsyncSession, user: User) -> tuple:
    from reports.cookie_view import build_cookie_inventory

    audit = await db.get(Audit, audit_id)
    if not audit or audit.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")
    consent_row = (await db.execute(select(Consent).where(Consent.audit_id == audit_id))).scalar_one_or_none()
    journey_row = (await db.execute(select(Journey).where(Journey.audit_id == audit_id))).scalar_one_or_none()
    consent = ConsentOut.model_validate(consent_row).model_dump(exclude={"report_view"}) if consent_row else None
    journey = ({"pages": journey_row.pages or [], "started_at": journey_row.started_at}
               if journey_row else None)
    return audit, build_cookie_inventory(consent, journey, audit.url)


@router.get("/{audit_id}/cookies")
async def audit_cookies(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cookie Scanner: every cookie found, with category, party, lifetime, flags, the page that set it and any issues."""
    _audit, inventory = await _cookie_inventory(audit_id, db, current_user)
    return inventory


@router.get("/{audit_id}/cookies.csv")
async def audit_cookies_csv(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from urllib.parse import urlparse

    from reports.cookie_view import inventory_csv

    audit, inventory = await _cookie_inventory(audit_id, db, current_user)
    host = (urlparse(audit.url).hostname or "site").replace(".", "-")
    return Response(
        content="\ufeff" + inventory_csv(inventory), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="cookies-{host}-audit-{audit.id}.csv"'},
    )


class FindingReviewIn(BaseModel):
    module: str = Field(..., max_length=40)
    title: str = Field(..., max_length=300)
    # "accepted" = intentional / approved choice (left out of score and priorities);
    # "to_verify" = keep, shown as "To be verified"; None = remove the mark.
    status: Optional[str] = Field(default=None, pattern="^(accepted|to_verify)$")
    note: str = Field(default="", max_length=2000)


async def _owned_completed(db: AsyncSession, audit_id: int, user: User) -> Audit:
    audit = await db.get(Audit, audit_id)
    if not audit or audit.user_id != user.id or audit.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")
    if audit.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The audit has not finished yet.")
    return audit


@router.get("/{audit_id}/findings/review")
async def list_finding_reviews(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Findings marked accepted / to verify for this audit's website (they apply to every audit of the site)."""
    from services.accepted_findings import marks_for_website

    audit = await _owned_completed(db, audit_id, current_user)
    marks = await marks_for_website(db, audit.website_id)
    return {"website_id": audit.website_id, "marks": list(marks.values())}


@router.post("/{audit_id}/findings/review")
async def review_finding(
    audit_id: int,
    payload: FindingReviewIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("audits")),
):
    """Marks a finding as accepted / to verify (or removes the mark) for the site, and updates this audit."""
    from models.history import HistoryEventType, log_event
    from services.accepted_findings import set_mark

    audit = await _owned_completed(db, audit_id, current_user)
    await set_mark(db, audit, current_user, payload.module, payload.title, payload.status, payload.note)
    verb = {"accepted": "accepted as intentional", "to_verify": "marked to be verified"}.get(
        payload.status or "", "un-marked")
    try:
        await log_event(db, current_user.id, HistoryEventType.FINDING_REVIEWED, description=f"Finding {verb}: {payload.title[:120]} ({audit.url})", audit_id=audit.id)
    except Exception:  # noqa: BLE001 — history is informational
        pass
    await db.commit()
    return {"overall": audit.overall_score, "raw_overall": audit.raw_overall_score,
            "breakdown": audit.breakdown, "raw_breakdown": audit.raw_breakdown}


@router.get("/{audit_id}", response_model=AuditOut)
async def get_audit(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    audit = await db.get(Audit, audit_id)
    if not audit or audit.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")
    return audit
