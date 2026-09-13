"""
schemas/history.py

Response models for api/history.py's two related but distinct views:

  * `HistoryPageOut` — the paginated audit-run history behind
    history.html (backed by models.audit.Audit, reusing `AuditOut`).

  * `ActivityEventOut` / `ActivityPageOut` — the broader account-activity
    feed (logins, audits started/completed, settings changes, schedule
    runs, ...) backed by models.history.History.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from schemas.audit import AuditOut


class HistoryPageOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[AuditOut]


class ActivityEventOut(BaseModel):
    id: int
    event_type: str
    description: str
    audit_id: Optional[int] = None
    meta: Optional[dict] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActivityPageOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ActivityEventOut]
