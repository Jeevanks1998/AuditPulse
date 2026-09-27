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
    bcc: List[EmailStr] = Field(default_factory=list)
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
    """
    One recorded send attempt. Carries the *entire* email — recipients
    (including bcc), subject, body, attachment keys — rather than a
    display summary, because the Email Reports page's "Resend" action
    reopens the composer prefilled from this payload, and any field left
    out here is a field the resend would silently lose.

    `audit_url` is denormalized in from the joined Audit row so the table
    can show a Website column without one extra request per row.
    """

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

    # Joined in by the service layer, not columns on models.ReportEmail.
    audit_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EmailHistoryStats(BaseModel):
    """The four counters above the Email Reports table (§10).

    Always computed across the account's whole history, never across the
    currently filtered page — a stat card that moved every time you typed
    in the search box would be reporting on the filter, not on the account.
    """

    total_sent: int = 0        # every attempt, successful or not
    successful: int = 0
    failed: int = 0
    reports_shared: int = 0    # distinct audits that were successfully emailed at least once


class EmailHistoryPage(BaseModel):
    total: int
    page: int
    page_size: int
    stats: EmailHistoryStats
    items: List[EmailHistoryOut]
