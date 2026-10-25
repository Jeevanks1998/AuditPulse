"""
Dashboard data (stats and recent audits). Queries live in audit_service.
"""

from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from models.audit import Audit
from models.user import User
from schemas.audit import AuditStatsOut
from schemas.dashboard import DashboardOut
from services import audit_service

DEFAULT_RECENT_LIMIT = 4


async def get_stats(db: AsyncSession, user: User) -> AuditStatsOut:
    return await audit_service.compute_stats(db, user)


async def get_recent(db: AsyncSession, user: User, limit: int = DEFAULT_RECENT_LIMIT) -> List[Audit]:
    return await audit_service.get_recent_audits(db, user, limit=limit)


async def get_summary(db: AsyncSession, user: User) -> DashboardOut:
    stats = await get_stats(db, user)
    recent = await get_recent(db, user)
    return DashboardOut(stats=stats, recent=recent)
