"""
api/dashboard.py

Aggregated view for dashboard.html: health-ring score, the four stat
cards, and the "recent audits" list. dashboard.js loads stats + recent
together via Promise.all, so `/dashboard/` returns both in one payload;
the split endpoints are kept too in case the frontend wants to fetch
them independently later. All the actual aggregation lives in
services.dashboard_service.
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import User, get_current_user
from config.database import get_db
from schemas.audit import AuditOut, AuditStatsOut
from schemas.dashboard import DashboardOut
from services import dashboard_service

router = APIRouter()


@router.get("/", response_model=DashboardOut)
async def dashboard_summary(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return await dashboard_service.get_summary(db, current_user)


@router.get("/stats", response_model=AuditStatsOut)
async def dashboard_stats(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return await dashboard_service.get_stats(db, current_user)


@router.get("/recent", response_model=List[AuditOut])
async def dashboard_recent(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return await dashboard_service.get_recent(db, current_user)
