"""
services/history_service.py

Business logic behind api/history.py's two related but distinct views:

  * Audit-run history behind history.html: search by hostname/label
    (mirrors historySearchInput in assets/js/history.js), paginate,
    fetch or delete a single record. Backed by models.audit.Audit.

  * A broader account-activity feed (logins, audits started/completed,
    settings changes, schedule runs, ...) backed by models.history.History.
    Additive: the frontend doesn't call this yet, but it gives a single
    place to show "everything that happened on this account" beyond just
    audit runs.
"""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit import Audit
from models.history import History, HistoryEventType, log_event
from models.user import User
from schemas.history import ActivityPageOut, HistoryPageOut


# --------------------------------------------------------------------------
# Audit history (existing behavior, now backed by models.audit.Audit)
# --------------------------------------------------------------------------
async def list_history(
    db: AsyncSession,
    user: User,
    q: Optional[str] = None,
    status_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> HistoryPageOut:
    filters = [Audit.user_id == user.id]
    if q:
        like = f"%{q.lower()}%"
        filters.append(or_(func.lower(Audit.url).like(like), func.lower(Audit.label).like(like)))
    if status_filter:
        filters.append(Audit.status == status_filter)

    total = await db.scalar(select(func.count()).select_from(Audit).where(*filters))

    result = await db.execute(
        select(Audit)
        .where(*filters)
        .order_by(Audit.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(result.scalars().all())

    return HistoryPageOut(total=total or 0, page=page, page_size=page_size, items=items)


async def list_activity(
    db: AsyncSession,
    user: User,
    event_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> ActivityPageOut:
    filters = [History.user_id == user.id]
    if event_type:
        filters.append(History.event_type == event_type)

    total = await db.scalar(select(func.count()).select_from(History).where(*filters))

    result = await db.execute(
        select(History)
        .where(*filters)
        .order_by(History.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(result.scalars().all())

    return ActivityPageOut(total=total or 0, page=page, page_size=page_size, items=items)


async def get_history_item(audit_id: int, db: AsyncSession, user: User) -> Audit:
    audit = await db.get(Audit, audit_id)
    if not audit or audit.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")
    return audit


async def delete_history_item(audit_id: int, db: AsyncSession, user: User) -> None:
    audit = await get_history_item(audit_id, db, user)

    await log_event(
        db,
        user.id,
        HistoryEventType.AUDIT_DELETED,
        description=f"Deleted audit of {audit.url} from history",
    )
    await db.delete(audit)
    await db.commit()
