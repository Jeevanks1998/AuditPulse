"""
services/dashboard_service.py

Aggregated view behind dashboard.html: health-ring score, the four stat
cards, and the "recent audits" list. dashboard.js loads stats + recent
together via Promise.all, so `get_summary` returns both in one payload;
`get_stats` / `get_recent` are kept too in case a route wants to fetch
them independently.

This is a thin wrapper — the actual queries live in services.audit_service
so "what counts as this user's audits" isn't duplicated across services.
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
