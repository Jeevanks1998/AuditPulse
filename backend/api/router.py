"""
api/router.py

Aggregates every domain router in api/ into a single APIRouter, which
main.py mounts once under settings.API_V1_PREFIX.
"""

from fastapi import APIRouter

from api import access_management, ai, audit, auth, dashboard, history, reports, scheduler, settings

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
# Server-to-server only (Access Portal -> AuditPulse), auth'd by a shared
# key rather than a user JWT — see access_management.verify_portal_key.
api_router.include_router(
    access_management.router, prefix="/internal/access", tags=["Access Portal (internal)"]
)
api_router.include_router(audit.router, prefix="/audits", tags=["Audits"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(history.router, prefix="/history", tags=["History"])
api_router.include_router(scheduler.router, prefix="/scheduler", tags=["Scheduler"])
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])
