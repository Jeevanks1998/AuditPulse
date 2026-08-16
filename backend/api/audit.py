"""
api/audit.py

Endpoints to start a run, poll its progress, and fetch a result. Parses
requests and shapes responses only — the create flow, query helpers, and
the background pipeline itself all live in services.audit_service, so
other callers (services.scheduler_service, a future Celery worker,
tests) can reuse them without going through HTTP.
"""

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from api.auth import User, get_current_user
from config.database import get_db
from models.analytics import Analytics
from models.audit import Audit
from models.consent import Consent
from schemas.audit import AnalyticsOut, AuditCreate, AuditOut, AuditProgressOut, AuditStatsOut, ConsentOut
from services import audit_service

router = APIRouter()


@router.post("/", response_model=AuditOut, status_code=status.HTTP_202_ACCEPTED)
async def start_audit(
    payload: AuditCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
