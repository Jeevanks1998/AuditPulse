"""
api/router.py

Aggregates every domain router in api/ into a single APIRouter, which
main.py mounts once under settings.API_V1_PREFIX.
"""

from fastapi import APIRouter

from api import ai, audit, auth, dashboard, history, reports, scheduler, settings

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(audit.router, prefix="/audits", tags=["Audits"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(history.router, prefix="/history", tags=["History"])
api_router.include_router(scheduler.router, prefix="/scheduler", tags=["Scheduler"])
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])
