"""
Response models for audit history (HistoryPageOut) and the activity feed (ActivityPageOut).
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
