"""
Report logic behind api/reports.py: report views, share links, exports
(JSON, HTML, PDF, evidence ZIP) and "Send to POC" email with its history.
The report content itself is built by reports/; exports are cached on disk.
"""

import secrets
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from crawler.screenshots import capture_screenshot
from emailer.attachments import ATTACHMENT_CHOICES
from emailer.service import send_report_email
from emailer.templates import build_body, build_subject
from models.analytics import Analytics
from models.audit import Audit
from models.consent import Consent
from models.history import HistoryEventType, log_event
from models.report import Report
from models.report_email import ReportEmail
from models.user import User
from pdf.pdf_generator import generate_pdf_report
from reports import build_report_payload, build_score_grid, render_html_report, to_json_report
from reports.evidence import build_evidence_zip, evidence_zip_filename
from reports.report_storage import load_html, load_json, load_pdf, save_html, save_json, save_pdf
from schemas.audit import AnalyticsOut, ConsentOut
from schemas.email import (
    EmailHistoryOut,
    EmailHistoryPage,
    EmailHistoryStats,
    EmailSendRequest,
    EmailSendResult,
)
from schemas.report import Finding, ReportOut, ScoreCell, ShareOut


async def get_owned_completed_audit(audit_id: int, db: AsyncSession, user: User) -> Audit:
    audit = await db.get(Audit, audit_id)
    if not audit or audit.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    if audit.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This audit hasn't finished running yet.",
        )
    return audit


async def get_report_row(audit_id: int, db: AsyncSession) -> Optional[Report]:
    result = await db.execute(select(Report).where(Report.audit_id == audit_id))
    return result.scalar_one_or_none()


async def _get_consent_dict(audit_id: int, db: AsyncSession) -> Optional[dict]:
    """Consent result in the same shape as GET /audits/{id}/consent, so every output agrees."""
    result = await db.execute(select(Consent).where(Consent.audit_id == audit_id))
    row = result.scalar_one_or_none()
    return ConsentOut.model_validate(row).model_dump() if row else None


async def _get_analytics_dict(audit_id: int, db: AsyncSession) -> Optional[dict]:
    result = await db.execute(select(Analytics).where(Analytics.audit_id == audit_id))
    row = result.scalar_one_or_none()
    return AnalyticsOut.model_validate(row).model_dump() if row else None


async def _get_journey_dict(audit_id: int, db: AsyncSession) -> Optional[dict]:
    from models.journey import Journey
    from schemas.audit import JourneyOut

    result = await db.execute(select(Journey).where(Journey.audit_id == audit_id))
    row = result.scalar_one_or_none()
    return JourneyOut.model_validate(row).model_dump() if row else None


async def get_report(audit_id: int, db: AsyncSession, user: User) -> ReportOut:
    """Returns the report and counts a view (only once it has been shared)."""
    audit = await get_owned_completed_audit(audit_id, db, user)
    breakdown = audit.breakdown or {}
    score_grid = [
        ScoreCell(module=c.module, label=c.label, score=c.score, target_section=c.target_section)
        for c in build_score_grid(breakdown)
    ]

    report = await get_report_row(audit_id, db)
    if report:
        report.view_count += 1
        await db.commit()

    return ReportOut(
        audit_id=audit.id,
        url=audit.url,
        overall=audit.overall_score or 0,
        generated_at=audit.completed_at.isoformat() if audit.completed_at else "",
        score_grid=score_grid,
        findings=[Finding(**f) for f in (audit.findings or [])],
        share_url=f"/public/report/{report.share_token}" if report and report.share_token else None,
        raw_overall=audit.raw_overall_score,
        raw_score_grid=([ScoreCell(module=c.module, label=c.label, score=c.score, target_section=c.target_section)
                         for c in build_score_grid(audit.raw_breakdown)] if audit.raw_breakdown else None),
    )


async def share_report(audit_id: int, db: AsyncSession, user: User) -> ShareOut:
    """Creates (or reuses) a share token."""
    audit = await get_owned_completed_audit(audit_id, db, user)

    report = await get_report_row(audit_id, db)
    if report is None:
        report = Report(audit_id=audit.id, user_id=user.id)
        db.add(report)

    if not report.share_token:
        report.share_token = secrets.token_urlsafe(12)
        report.is_public = True
        await log_event(
            db,
            user.id,
            HistoryEventType.REPORT_SHARED,
            description=f"Shared the report for {audit.url}",
            audit_id=audit.id,
        )

    await db.commit()
    return ShareOut(share_url=f"/public/report/{report.share_token}")


# Full payload (with AI sections), used by the exports
async def _build_full_payload(audit_id: int, db: AsyncSession, user: User):
    audit = await get_owned_completed_audit(audit_id, db, user)
    report = await get_report_row(audit_id, db)
    share_url = f"/public/report/{report.share_token}" if report and report.share_token else None

    consent = await _get_consent_dict(audit_id, db)
    analytics = await _get_analytics_dict(audit_id, db)
    journey = await _get_journey_dict(audit_id, db)

    payload = await build_report_payload(
        audit_id=audit.id,
        url=audit.url,
        overall=audit.overall_score or 0,
        generated_at=audit.completed_at.isoformat() if audit.completed_at else "",
        breakdown=audit.breakdown or {},
        findings=audit.findings or [],
        share_url=share_url,
        consent=consent,
        analytics=analytics,
        journey=journey,
        raw_overall=audit.raw_overall_score,
    )
    # Bring back screenshots the server disk lost since the audit ran.
    from utils.screenshot_store import restore_for_payload
    await restore_for_payload(payload)
    return payload


async def export_report_json(audit_id: int, db: AsyncSession, user: User, force_refresh: bool = False) -> dict:
    """JSON export (cached unless `force_refresh`)."""
    await get_owned_completed_audit(audit_id, db, user)  # ownership check even when cached

    if not force_refresh:
        cached = load_json(audit_id)
        if cached is not None:
            return cached

    payload = await _build_full_payload(audit_id, db, user)
    data = to_json_report(payload)
    save_json(audit_id, data)
    return data


async def export_report_html(audit_id: int, db: AsyncSession, user: User, force_refresh: bool = False) -> str:
    """HTML export (cached unless `force_refresh`)."""
    await get_owned_completed_audit(audit_id, db, user)  # ownership check even when cached

    if not force_refresh:
        cached = load_html(audit_id)
        if cached is not None:
            return cached

    payload = await _build_full_payload(audit_id, db, user)
    html = render_html_report(payload)
    save_html(audit_id, html)
    return html


async def export_report_pdf(audit_id: int, db: AsyncSession, user: User, force_refresh: bool = False) -> bytes:
    """PDF export (cached unless `force_refresh`)."""
    audit = await get_owned_completed_audit(audit_id, db, user)

    if not force_refresh:
        cached = load_pdf(audit_id)
        if cached is not None:
            return cached

    payload = await _build_full_payload(audit_id, db, user)
    screenshot_path = await _resolve_screenshot_path(audit)
    pdf_bytes = generate_pdf_report(payload, screenshot_path=screenshot_path)
    save_pdf(audit_id, pdf_bytes)
    return pdf_bytes


async def _resolve_screenshot_path(audit: Audit) -> Optional[str]:
    """Homepage screenshot for the PDF (no longer used)."""
    # The PDF no longer has a homepage preview, so don't start a browser for one.
    return None


# Evidence ZIP
async def export_evidence_zip(audit_id: int, db: AsyncSession, user: User) -> tuple[bytes, str]:
    """Returns (zip_bytes, filename): the PDF plus all screenshots and evidence JSON for this audit."""
    audit = await get_owned_completed_audit(audit_id, db, user)
    pdf_bytes = load_pdf(audit_id)
    payload = await _build_full_payload(audit_id, db, user)
    if pdf_bytes is None:
        screenshot_path = await _resolve_screenshot_path(audit)
        pdf_bytes = generate_pdf_report(payload, screenshot_path=screenshot_path)
        save_pdf(audit_id, pdf_bytes)

    zip_bytes = build_evidence_zip(payload, pdf_bytes=pdf_bytes)
    return zip_bytes, evidence_zip_filename(audit_id)


# "Send to POC" email and Email History
def get_attachment_choices() -> dict:
    """Attachment options for the dialog (from emailer.attachments)."""
    return dict(ATTACHMENT_CHOICES)


async def send_report_to_poc(
    audit_id: int, request: EmailSendRequest, db: AsyncSession, user: User,
    body_intro: Optional[str] = None,
) -> EmailSendResult:
    """Sends the report and records the attempt in Email History, whether it worked or not."""
    audit = await get_owned_completed_audit(audit_id, db, user)
    payload = await _build_full_payload(audit_id, db, user)

    pdf_bytes = None
    if "pdf" in request.attachments or "evidence_zip" in request.attachments:
        pdf_bytes = load_pdf(audit_id)
        if pdf_bytes is None:
            screenshot_path = await _resolve_screenshot_path(audit)
            pdf_bytes = generate_pdf_report(payload, screenshot_path=screenshot_path)
            save_pdf(audit_id, pdf_bytes)

    subject = request.subject or ""
    if body_intro and not request.body:
        # Scheduled email: the schedule's note goes above the standard summary.
        request = request.model_copy(update={
            "body": body_intro.strip() + "\n\n" + build_body(payload, poc_name="there")
        })
    outcome = await send_report_email(
        payload=payload,
        audit_id=audit_id,
        to=[str(addr) for addr in request.to],
        cc=[str(addr) for addr in request.cc],
        bcc=[str(addr) for addr in request.bcc],
        subject=request.subject,
        body=request.body,
        attachment_keys=request.attachments,
        pdf_bytes=pdf_bytes,
        poc_name="there",
    )

    # Record what was actually sent (defaults when the caller left them empty), so Resend isn't blank.
    sent_subject = subject or build_subject(payload)
    sent_body = request.body or build_body(payload, poc_name="there")

    email_row = ReportEmail(
        audit_id=audit_id,
        user_id=user.id,
        recipient_to=[str(addr) for addr in request.to],
        recipient_cc=[str(addr) for addr in request.cc],
        # BCC is stored for Resend but only shown to the owner.
        recipient_bcc=[str(addr) for addr in request.bcc],
        subject=sent_subject,
        body=sent_body,
        # On failure nothing was attached, so record what was asked for (so a retry keeps them).
        attachments=outcome.attached_keys or list(request.attachments),
        status=outcome.status,
        error_message=outcome.error_message,
        sent_at=outcome.sent_at,
    )
    db.add(email_row)

    if outcome.success:
        await log_event(
            db,
            user.id,
            HistoryEventType.REPORT_SHARED,
            description=f"Emailed the report for {audit.url} to {', '.join(email_row.recipient_to)}",
            audit_id=audit.id,
        )

    await db.commit()

    return EmailSendResult(
        success=outcome.success,
        status=outcome.status,
        error_message=outcome.error_message,
        sent_at=outcome.sent_at,
    )


def _to_history_out(row: ReportEmail, audit_url: Optional[str]) -> EmailHistoryOut:
    """One ReportEmail row for the API. Missing values on older rows become [] or "", so Resend still works."""
    return EmailHistoryOut(
        id=row.id,
        audit_id=row.audit_id,
        user_id=row.user_id,
        recipient_to=list(row.recipient_to or []),
        recipient_cc=list(row.recipient_cc or []),
        recipient_bcc=list(row.recipient_bcc or []),
        subject=row.subject or "",
        body=row.body or "",
        attachments=list(row.attachments or []),
        status=row.status,
        error_message=row.error_message,
        sent_at=row.sent_at,
        audit_url=audit_url,
    )


async def get_email_history(audit_id: int, db: AsyncSession, user: User) -> list[EmailHistoryOut]:
    """Every "Send to POC" attempt for this audit, newest first."""
    audit = await get_owned_completed_audit(audit_id, db, user)
    result = await db.execute(
        select(ReportEmail)
        .where(ReportEmail.audit_id == audit_id)
        .order_by(ReportEmail.sent_at.desc())
    )
    return [_to_history_out(row, audit.url) for row in result.scalars().all()]


async def _email_history_stats(db: AsyncSession, user: User) -> EmailHistoryStats:
    """The four counters above the table, for the whole account (not the current filter)."""
    grouped = await db.execute(
        select(ReportEmail.status, func.count(ReportEmail.id))
        .where(ReportEmail.user_id == user.id)
        .group_by(ReportEmail.status)
    )
    by_status = {status_value: count for status_value, count in grouped.all()}

    shared = await db.execute(
        select(func.count(distinct(ReportEmail.audit_id))).where(
            ReportEmail.user_id == user.id, ReportEmail.status == "sent"
        )
    )

    successful = by_status.get("sent", 0)
    failed = by_status.get("failed", 0)
    return EmailHistoryStats(
        # Sum all statuses so unknown ones still count in the total.
        total_sent=sum(by_status.values()),
        successful=successful,
        failed=failed,
        reports_shared=shared.scalar_one() or 0,
    )


async def list_email_history(
    db: AsyncSession,
    user: User,
    *,
    q: Optional[str] = None,
    status_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
) -> EmailHistoryPage:
    """Email History for the whole account (Email Reports page), filtered and paged
    in SQL. Only this user's sends.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    base = (
        select(ReportEmail, Audit.url)
        .join(Audit, Audit.id == ReportEmail.audit_id, isouter=True)
        .where(ReportEmail.user_id == user.id)
    )

    if status_filter in ("sent", "failed"):
        base = base.where(ReportEmail.status == status_filter)

    if q:
        # Search covers website and subject (recipients are searched in the browser).
        like = f"%{q.strip()}%"
        base = base.where(or_(Audit.url.ilike(like), ReportEmail.subject.ilike(like)))

    total = await db.execute(
        select(func.count()).select_from(base.order_by(None).subquery())
    )

    rows = await db.execute(
        base.order_by(ReportEmail.sent_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    return EmailHistoryPage(
        total=total.scalar_one() or 0,
        page=page,
        page_size=page_size,
        stats=await _email_history_stats(db, user),
        items=[_to_history_out(row, audit_url) for row, audit_url in rows.all()],
    )


async def get_email_record(email_id: int, db: AsyncSession, user: User) -> EmailHistoryOut:
    """One sent email in full (for View and Resend). Another account's row is a 404."""
    result = await db.execute(
        select(ReportEmail, Audit.url)
        .join(Audit, Audit.id == ReportEmail.audit_id, isouter=True)
        .where(ReportEmail.id == email_id, ReportEmail.user_id == user.id)
    )
    found = result.first()
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email record not found")

    row, audit_url = found
    return _to_history_out(row, audit_url)
