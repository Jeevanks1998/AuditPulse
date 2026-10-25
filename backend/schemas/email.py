"""
Request/response models for "Send to POC" and Email History.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class EmailSendRequest(BaseModel):
    # Limits so this can't be used to mass-mail.
    to: List[EmailStr] = Field(min_length=1, max_length=20)
    cc: List[EmailStr] = Field(default_factory=list, max_length=20)
    bcc: List[EmailStr] = Field(default_factory=list, max_length=20)
    subject: Optional[str] = Field(default=None, max_length=300)
    body: Optional[str] = Field(default=None, max_length=20_000)
    # Attachment keys (e.g. ["pdf", "evidence_zip"]). Defaults to just the PDF.
    attachments: List[str] = Field(default_factory=lambda: ["pdf"], max_length=10)

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
    """One sent email in full (incl. BCC and body), so Resend can reload it. audit_url is added for the table."""

    id: int
    audit_id: int
    user_id: int
    recipient_to: List[str]
    recipient_cc: List[str]
    recipient_bcc: List[str] = Field(default_factory=list)
    subject: str
    body: str = ""
    attachments: List[str] = Field(default_factory=list)
    status: str
    error_message: Optional[str] = None
    sent_at: datetime

    # Added by the service, not database columns.
    audit_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EmailHistoryStats(BaseModel):
    """The four counters on the Email Reports page, always for the whole account (not the filtered view)."""

    total_sent: int = 0        # every attempt
    successful: int = 0
    failed: int = 0
    reports_shared: int = 0    # audits emailed successfully at least once


class EmailHistoryPage(BaseModel):
    total: int
    page: int
    page_size: int
    stats: EmailHistoryStats
    items: List[EmailHistoryOut]
