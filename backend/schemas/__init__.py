"""
schemas/

Pydantic request/response models for the AuditPulse backend, in one
package so every api/ router has a single, obvious import path for the
data shapes it sends/receives (business logic — routes, pipelines, query
helpers — stays in api/). Mirrors the `models/` package's role for
SQLAlchemy ORM classes.

Not every router's schemas live here: api/settings.py and api/scheduler.py
define their own (SettingsOut/SettingsUpdate/ApiKeyOut/ExportOut and
Schedule's ScheduleCreate/ScheduleUpdate/ScheduleOut) because those are
tightly local to a single route module rather than shared across several,
the way audit/report/user/dashboard/history shapes are.
"""

from schemas.audit import AuditCreate, AuditOut, AuditProgressOut, AuditStatsOut
from schemas.dashboard import DashboardOut
from schemas.history import ActivityEventOut, ActivityPageOut, HistoryPageOut
from schemas.report import Finding, MODULE_LABELS, ReportOut, ScoreCell, ShareOut
from schemas.user import TokenOut, UserLogin, UserOut, UserRegister

__all__ = [
    "AuditCreate",
    "AuditOut",
    "AuditProgressOut",
    "AuditStatsOut",
    "DashboardOut",
    "ActivityEventOut",
    "ActivityPageOut",
    "HistoryPageOut",
    "Finding",
    "MODULE_LABELS",
    "ReportOut",
    "ScoreCell",
    "ShareOut",
    "TokenOut",
    "UserLogin",
    "UserOut",
    "UserRegister",
]
