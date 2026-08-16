"""
schemas/report.py

Response models for api/reports.py: the score grid feeding report.html's
radar chart (assets/js/report.js -> Charts.renderRadar), the findings
list, and the share-link payload returned by the "Share report" action.
"""

from typing import List, Optional

from pydantic import BaseModel

MODULE_LABELS = {
    "seo": "SEO",
    "performance": "Performance",
    "accessibility": "Accessibility",
    "security": "Security",
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
