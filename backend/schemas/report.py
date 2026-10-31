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
    recommendation: Optional[str] = None
    # Set when the site's team marked it: {"status": "accepted" | "to_verify", "note", "by", "at"}.
    review: Optional[dict] = None
    # The measured severity of a finding marked "to verify" (shown as info).
    original_severity: Optional[str] = None


class ReportOut(BaseModel):
    audit_id: int
    url: str
    overall: int
    generated_at: str
    score_grid: List[ScoreCell]
    findings: List[Finding]
    share_url: Optional[str] = None
    # Scores as measured, before accepted findings were taken out (None if nothing was marked).
    raw_overall: Optional[int] = None
    raw_score_grid: Optional[List[ScoreCell]] = None


class ShareOut(BaseModel):
    share_url: str
