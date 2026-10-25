"""
Sends report emails over SMTP (settings.SMTP_*, from the environment only).
Runs smtplib in a thread so it doesn't block. Never raises: always returns
an outcome so it can be logged in Email History.
"""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from config.logging import logger
from config.settings import settings
from emailer.attachments import ResolvedAttachment, resolve_attachments
from emailer.templates import build_body, build_subject
from reports.generator import ReportPayload


@dataclass
class EmailSendOutcome:
    success: bool
    status: str  # "sent" | "failed"
    error_message: Optional[str]
    sent_at: datetime
    attached_keys: List[str]


async def send_report_email(
    *,
    payload: ReportPayload,
    audit_id: int,
    to: List[str],
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    attachment_keys: Optional[List[str]] = None,
    pdf_bytes: Optional[bytes] = None,
    poc_name: str = "there",
) -> EmailSendOutcome:
    """Emails the report to a POC. Always returns an outcome, never raises."""
    now = datetime.now(timezone.utc)

    if not settings.EMAIL_ENABLED:
        return EmailSendOutcome(
            success=False,
            status="failed",
            error_message="Email sending isn't configured yet — set SMTP_HOST (and credentials) in the backend environment.",
            sent_at=now,
            attached_keys=[],
        )

    if not to:
        return EmailSendOutcome(
            success=False, status="failed", error_message="At least one recipient is required.",
            sent_at=now, attached_keys=[],
        )

    resolved_attachments = resolve_attachments(
        attachment_keys or ["pdf"], payload, audit_id=audit_id, pdf_bytes=pdf_bytes
    )
    attached_keys = attachment_keys or ["pdf"]

    message = _build_mime_message(
        to=to,
        cc=cc or [],
        subject=subject or build_subject(payload),
        body=body or build_body(payload, poc_name=poc_name),
        attachments=resolved_attachments,
    )

    # BCC only goes in the SMTP envelope, never in the headers, so it stays hidden.
    envelope_recipients = to + (cc or []) + (bcc or [])

    try:
        await asyncio.to_thread(_send_via_smtp, message, envelope_recipients)
    except Exception as exc:  # noqa: BLE001 — any SMTP/network failure should surface as a recorded failure, not a 500
        logger.warning(f"emailer.service: send failed for audit {audit_id}: {exc}")
        return EmailSendOutcome(
            success=False, status="failed", error_message=str(exc), sent_at=now, attached_keys=[],
        )

    return EmailSendOutcome(success=True, status="sent", error_message=None, sent_at=now, attached_keys=attached_keys)


async def send_plain_email(*, to: List[str], subject: str, body: str) -> EmailSendOutcome:
    """Short text email with no attachments (e.g. "audit finished"). Never raises."""
    now = datetime.now(timezone.utc)
    if not settings.EMAIL_ENABLED:
        return EmailSendOutcome(False, "failed", "Email sending isn't configured (SMTP_HOST is empty).", now, [])
    if not to:
        return EmailSendOutcome(False, "failed", "At least one recipient is required.", now, [])
    message = _build_mime_message(to=to, cc=[], subject=subject, body=body, attachments=[])
    try:
        await asyncio.to_thread(_send_via_smtp, message, to)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"emailer.service: plain email to {', '.join(to)} failed: {exc}")
        return EmailSendOutcome(False, "failed", str(exc), now, [])
    return EmailSendOutcome(True, "sent", None, now, [])


def _build_mime_message(
    *, to: List[str], cc: List[str], subject: str, body: str, attachments: List[ResolvedAttachment]
) -> MIMEMultipart:
    message = MIMEMultipart()
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    for attachment in attachments:
        part = MIMEApplication(attachment.content, Name=attachment.filename)
        part["Content-Disposition"] = f'attachment; filename="{attachment.filename}"'
        message.attach(part)

    return message


def _send_via_smtp(message: MIMEMultipart, recipients: List[str]) -> None:
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.sendmail(settings.SMTP_FROM_EMAIL, recipients, message.as_string())
