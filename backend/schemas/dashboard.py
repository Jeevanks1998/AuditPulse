"""
Dashboard response: stats and recent audits together.
"""

from typing import List

from pydantic import BaseModel

from schemas.audit import AuditOut, AuditStatsOut


class DashboardOut(BaseModel):
    stats: AuditStatsOut
    recent: List[AuditOut]
