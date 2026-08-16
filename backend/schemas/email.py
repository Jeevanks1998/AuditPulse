"""
schemas/email.py

Request/response models for the POC email endpoints in api/reports.py
(§9.1 Send to POC UI, §10 Email History). `EmailSendRequest.attachments`
is a list of the attachment keys emailer.attachments.ATTACHMENT_CHOICES
exposes (§9.2) — the frontend's checkbox list sends back whichever the
user left checked, never a hardcoded set (§14: "Do not hardcode
vendor-specific results" applies equally to attachment choices).
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class EmailSendRequest(BaseModel):
    to: List[EmailStr] = Field(min_length=1)
    cc: List[EmailStr] = Field(default_factory=list)
    subject: Optional[str] = None
    body: Optional[str] = None
    # Keys from emailer.attachments.ATTACHMENT_CHOICES, e.g.
    # ["pdf", "consent_screenshots", "analytics_runtime", "cookie_evidence",
    #  "network_evidence", "evidence_zip"]. Defaults to just the PDF if
    # the caller sends nothing — never silently attaches everything.
    attachments: List[str] = Field(default_factory=lambda: ["pdf"])

    @field_validator("attachments")
    @classmethod
    def _non_empty_attachments(cls, v: List[str]) -> List[str]:
        return v or ["pdf"]


class EmailSendResult(BaseModel):
    success: bool
    status: str  # "sent" | "failed"
    error_message: Optional[str] = None
    sent_at: datetime


class EmailHistoryOut(BaseModel):
    id: int
    audit_id: int
    recipient_to: List[str]
    recipient_cc: List[str]
    subject: str
    status: str
    error_message: Optional[str] = None
    sent_at: datetime

    model_config = ConfigDict(from_attributes=True)
