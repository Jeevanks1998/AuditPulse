"""
services/report_service.py

Business logic behind api/reports.py: read-only report views built on
top of a completed Audit (models/audit.py). Shapes data the way
report.html expects it — a score grid for the radar chart (see
assets/js/report.js -> Charts.renderRadar) and findings grouped by
module/severity — plus the share / export actions behind the banner
buttons (shareReportBtn, downloadPdfBtn), backed by the persisted Report
model (models/report.py) so share links can be revoked/expired and view
counts tracked.

The score grid + AI layer (executive summary, prioritized findings,
business impact, action plan) are built by reports.generator rather than
here — this module only knows about the Audit/Report ORM rows and the
FastAPI-facing request/response shapes; reports/ has no idea SQLAlchemy
or HTTPException exist. json/html/pdf export bodies go through
reports.json_report / reports.html_report / pdf.pdf_generator and are
cached to disk via reports.report_storage so a repeat download doesn't
re-run the AI pipeline in reports.generator (or, for the PDF, redraw
every chart on top of that).
"""

import secrets
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from crawler.screenshots import capture_screenshot
from emailer.attachments import ATTACHMENT_CHOICES
from emailer.service import send_report_email
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
from schemas.email import EmailHistoryOut, EmailSendRequest, EmailSendResult
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
    """Same row api/audit.py's GET /audits/{id}/consent reads, shaped identically (ConsentOut) so
    every consumer of `consent` (report page, PDF, evidence ZIP, POC email) agrees on one shape (§8)."""
    result = await db.execute(select(Consent).where(Consent.audit_id == audit_id))
    row = result.scalar_one_or_none()
    return ConsentOut.model_validate(row).model_dump() if row else None


async def _get_analytics_dict(audit_id: int, db: AsyncSession) -> Optional[dict]:
    result = await db.execute(select(Analytics).where(Analytics.audit_id == audit_id))
    row = result.scalar_one_or_none()
    return AnalyticsOut.model_validate(row).model_dump() if row else None


async def get_report(audit_id: int, db: AsyncSession, user: User) -> ReportOut:
    """
    Fetches the completed audit + its shaped report payload, bumping the
    Report row's view_count (if one exists — a report only gets a row
    once it's been shared, see `share_report`).
    """
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
    )


async def share_report(audit_id: int, db: AsyncSession, user: User) -> ShareOut:
    """Mints (or reuses) a share token for a completed audit's report."""
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


# --------------------------------------------------------------------------
# Full (AI-enriched) payload — shared by the json/html export endpoints
# --------------------------------------------------------------------------
async def _build_full_payload(audit_id: int, db: AsyncSession, user: User):
    audit = await get_owned_completed_audit(audit_id, db, user)
    report = await get_report_row(audit_id, db)
    share_url = f"/public/report/{report.share_token}" if report and report.share_token else None

    consent = await _get_consent_dict(audit_id, db)
    analytics = await _get_analytics_dict(audit_id, db)

    return await build_report_payload(
        audit_id=audit.id,
        url=audit.url,
        overall=audit.overall_score or 0,
        generated_at=audit.completed_at.isoformat() if audit.completed_at else "",
        breakdown=audit.breakdown or {},
        findings=audit.findings or [],
        share_url=share_url,
        consent=consent,
        analytics=analytics,
    )


async def export_report_json(audit_id: int, db: AsyncSession, user: User, force_refresh: bool = False) -> dict:
    """Returns the full JSON export (reports.json_report), using the on-disk cache unless `force_refresh`."""
    await get_owned_completed_audit(audit_id, db, user)  # 404/409 check even on a cache hit

    if not force_refresh:
        cached = load_json(audit_id)
        if cached is not None:
            return cached

    payload = await _build_full_payload(audit_id, db, user)
    data = to_json_report(payload)
    save_json(audit_id, data)
    return data


async def export_report_html(audit_id: int, db: AsyncSession, user: User, force_refresh: bool = False) -> str:
    """Returns the full standalone HTML export (reports.html_report), using the on-disk cache unless `force_refresh`."""
    await get_owned_completed_audit(audit_id, db, user)  # 404/409 check even on a cache hit

    if not force_refresh:
        cached = load_html(audit_id)
        if cached is not None:
            return cached

    payload = await _build_full_payload(audit_id, db, user)
    html = render_html_report(payload)
    save_html(audit_id, html)
    return html


async def export_report_pdf(audit_id: int, db: AsyncSession, user: User, force_refresh: bool = False) -> bytes:
    """Returns the full PDF export (pdf.pdf_generator), using the on-disk cache unless `force_refresh`.

    Same shape as export_report_json/export_report_html above; the only
    extra step is resolving a homepage screenshot to embed
    (pdf/screenshots.py), which is itself best-effort — see
    `_resolve_screenshot_path`.
    """
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
    """Best-effort homepage screenshot for the PDF's "Page Preview" section.

    Gated on settings.CRAWLER_ENABLE_SCREENSHOTS — the same flag the
    crawler itself checks — since capture requires the optional Playwright
    dependency; `capture_screenshot` already returns None on any failure
    (missing browser binary, navigation timeout, etc.) rather than
    raising, so a bad capture never blocks the PDF.
    """
    if not settings.CRAWLER_ENABLE_SCREENSHOTS:
        return None
    return await capture_screenshot(audit.url, filename_hint=f"audit-{audit.id}")


# --------------------------------------------------------------------------
# Evidence ZIP export (§5.2)
# --------------------------------------------------------------------------
async def export_evidence_zip(audit_id: int, db: AsyncSession, user: User) -> tuple[bytes, str]:
    """
    Returns `(zip_bytes, filename)` for the complete evidence package —
    the PDF plus every screenshot, cookie, and network-evidence JSON file
    captured for this audit (§5.2). Always builds the PDF fresh from the
    cache (or renders it if nothing's cached yet) so the ZIP's PDF and its
    JSON evidence describe the exact same audit run.
    """
    audit = await get_owned_completed_audit(audit_id, db, user)
    pdf_bytes = load_pdf(audit_id)
    payload = await _build_full_payload(audit_id, db, user)
    if pdf_bytes is None:
        screenshot_path = await _resolve_screenshot_path(audit)
        pdf_bytes = generate_pdf_report(payload, screenshot_path=screenshot_path)
        save_pdf(audit_id, pdf_bytes)

    zip_bytes = build_evidence_zip(payload, pdf_bytes=pdf_bytes)
    return zip_bytes, evidence_zip_filename(audit_id)


# --------------------------------------------------------------------------
# POC Email workflow (§9) + Email History (§10)
# --------------------------------------------------------------------------
def get_attachment_choices() -> dict:
    """The checkbox options the "Send to POC" modal renders (§9.2) — sourced from
    emailer.attachments so the frontend never hardcodes the list (§14)."""
    return dict(ATTACHMENT_CHOICES)


async def send_report_to_poc(
    audit_id: int, request: EmailSendRequest, db: AsyncSession, user: User
) -> EmailSendResult:
    """
    Sends the report to the requested recipients (§9.1) and records the
    attempt — success or failure — as an Email History row (§10)
    regardless of outcome, so a failed send is still visible/diagnosable
    from report.html rather than silently lost.
    """
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
    outcome = await send_report_email(
        payload=payload,
        audit_id=audit_id,
        to=[str(addr) for addr in request.to],
        cc=[str(addr) for addr in request.cc],
        subject=request.subject,
        body=request.body,
        attachment_keys=request.attachments,
        pdf_bytes=pdf_bytes,
        poc_name="there",
        user_name=user.name or "AuditPulse",
    )

    email_row = ReportEmail(
        audit_id=audit_id,
        user_id=user.id,
        recipient_to=[str(addr) for addr in request.to],
        recipient_cc=[str(addr) for addr in request.cc],
        subject=subject or f"Website Audit Report — {audit.url}",
        attachments=outcome.attached_keys,
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


async def get_email_history(audit_id: int, db: AsyncSession, user: User) -> list[EmailHistoryOut]:
    """Every "Send to POC" attempt for this audit (§10), most recent first."""
    await get_owned_completed_audit(audit_id, db, user)
    result = await db.execute(
        select(ReportEmail)
        .where(ReportEmail.audit_id == audit_id)
        .order_by(ReportEmail.sent_at.desc())
    )
    rows = result.scalars().all()
    return [EmailHistoryOut.model_validate(row) for row in rows]
