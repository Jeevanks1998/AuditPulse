"""
schemas/dashboard.py

Aggregated response model for dashboard.html: dashboard.js loads stats
and the recent-audits list together via Promise.all, so `/dashboard/`
returns both in a single `DashboardOut` payload (api/dashboard.py).
"""

from typing import List

from pydantic import BaseModel

from schemas.audit import AuditOut, AuditStatsOut


class DashboardOut(BaseModel):
    stats: AuditStatsOut
    recent: List[AuditOut]
