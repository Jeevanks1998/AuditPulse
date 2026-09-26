"""
schemas/dashboard.py

Aggregated response model for dashboard.html: dashboard.js loads stats
and the recent-audits list together via Promise.all, so `/dashboard/`
returns both in a single `DashboardOut` payload (api/dashboard.py).
"""

from typing import List

from pydantic import BaseModel

from schemas.audit import AuditOut, AuditStatsOut


class RegionSummaryOut(BaseModel):
    """
    Counts of completed, consent-scanned audits by which regional
    framework applied (services.audit_service.compute_region_summary) —
    kept as three separate buckets rather than one combined number,
    since a GDPR failure and a CCPA failure aren't the same finding and
    collapsing them together would hide which regulation is actually at
    risk. "not_assessed" covers audits with no consent module run at
    all, or where region detection couldn't resolve a framework
    (unknown/unrecognized region) — never counted as a failure of
    either framework.
    """
    gdpr: int
    ccpa: int
    not_assessed: int


class DashboardOut(BaseModel):
    stats: AuditStatsOut
    recent: List[AuditOut]
    region_summary: RegionSummaryOut
