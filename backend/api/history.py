"""
api/history.py

Two related but distinct views, both backed by services.history_service:

  * `/history/` etc. — the audit-run history behind history.html: search
    by hostname/label (mirrors historySearchInput in assets/js/history.js),
    paginate, fetch or delete a single record.

  * `/history/activity` — a broader account-activity feed (logins, audits
    started/completed, settings changes, schedule runs, ...). Additive:
    the frontend doesn't call this yet, but it gives a single place to
    show "everything that happened on this account" beyond just audit
    runs.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import User, get_current_user
from config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from config.database import get_db
from schemas.audit import AuditOut
from schemas.history import ActivityPageOut, HistoryPageOut
from services import history_service

router = APIRouter()


@router.get("/", response_model=HistoryPageOut)
async def list_history(
    q: Optional[str] = Query(default=None, description="Search by URL or label"),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await history_service.list_history(
        db, current_user, q=q, status_filter=status_filter, page=page, page_size=page_size
    )


@router.get("/activity", response_model=ActivityPageOut)
async def list_activity(
    event_type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await history_service.list_activity(
        db, current_user, event_type=event_type, page=page, page_size=page_size
    )


@router.get("/{audit_id}", response_model=AuditOut)
async def get_history_item(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await history_service.get_history_item(audit_id, db, current_user)


@router.delete("/{audit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_history_item(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await history_service.delete_history_item(audit_id, db, current_user)
