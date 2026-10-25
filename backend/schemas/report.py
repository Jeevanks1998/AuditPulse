"""
Response models for reports: score grid, findings and share links.
"""

from typing import List, Optional

from pydantic import BaseModel

MODULE_LABELS = {
    "analytics": "Analytics",
    "consent": "Consent",
    "journey": "Journey Map",
}


class ScoreCell(BaseModel):
    module: str
    label: str
    score: int
    target_section: str


class Finding(BaseModel):
    module: str
    severity: str
    title: str
    description: str


class ReportOut(BaseModel):
    audit_id: int
    url: str
    overall: int
    generated_at: str
    score_grid: List[ScoreCell]
    findings: List[Finding]
    share_url: Optional[str] = None


class ShareOut(BaseModel):
    share_url: str
