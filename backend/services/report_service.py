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
        bcc=[str(addr) for addr in request.bcc],
        subject=request.subject,
        body=request.body,
        attachment_keys=request.attachments,
        pdf_bytes=pdf_bytes,
        poc_name="there",
    )

    # What actually went out — the composer usually supplies both, but a
    # caller that omits them gets emailer.templates' defaults, so record
    # those rather than an empty string. Otherwise a resend of this row
    # would open on a blank body.
    sent_subject = subject or build_subject(payload)
    sent_body = request.body or build_body(payload, poc_name="there")

    email_row = ReportEmail(
        audit_id=audit_id,
        user_id=user.id,
        recipient_to=[str(addr) for addr in request.to],
        recipient_cc=[str(addr) for addr in request.cc],
        # Bcc stays out of the outgoing message's headers (emailer.service
        # puts it in the SMTP envelope only, or it stops being blind) but is
        # recorded here so "Resend" repeats the same email rather than a
        # quietly narrower one. Only ever returned to this row's own owner.
        recipient_bcc=[str(addr) for addr in request.bcc],
        subject=sent_subject,
        body=sent_body,
        # On success this is what was really attached (emailer.attachments
        # drops keys with no data for this audit). On a failure nothing was
        # attached at all, so fall back to what was *asked* for — otherwise
        # retrying a failed send would come back with no attachments.
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
    """Shapes one ReportEmail row for the API, folding in the audit's URL.

    Every JSON column is coerced through `or []` / `or ""`: rows written
    before the recipient_bcc/body migration have those columns at their
    server defaults, and a row written before *any* of this had NULLs.
    The composer prefills straight from this payload, so a None reaching
    it would break "Resend" on exactly the oldest rows.
    """
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
    """Every "Send to POC" attempt for this audit (§10), most recent first."""
    audit = await get_owned_completed_audit(audit_id, db, user)
    result = await db.execute(
        select(ReportEmail)
        .where(ReportEmail.audit_id == audit_id)
        .order_by(ReportEmail.sent_at.desc())
    )
    return [_to_history_out(row, audit.url) for row in result.scalars().all()]


async def _email_history_stats(db: AsyncSession, user: User) -> EmailHistoryStats:
    """
    The four counters above the table. Deliberately unfiltered — these
    describe the account, not the current search, so they hold still while
    the user filters the table underneath them.

    One grouped query for the status split plus one for the distinct-audit
    count, rather than four COUNT(*)s or (worse) counting in Python over
    every row the account has ever sent.
    """
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
        # Sum the grouped counts rather than hardcoding sent+failed, so a
        # status this code doesn't know about yet still lands in the total.
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
    """
    Account-wide Email History for email-reports.html (§10).

    The per-audit endpoint can't back that page: it would cost one request
    per audit and could still only show audits the caller already knew to
    ask about. This joins ReportEmail to Audit once so each row carries the
    website it belongs to, and filters/paginates in SQL.

    Scoped by ReportEmail.user_id, so one account never sees another's
    sends even where both audited the same URL.
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
        # Recipients live in a JSON column, which no portable SQL operator
        # can search by element, so the text filter covers the two plain
        # string columns (website + subject). Recipient search is done on
        # the client against the rows already on screen.
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
    """
    One recorded send, in full — what "View" opens and what "Resend"
    prefills the composer from.

    A row belonging to another account is a 404 rather than a 403: the
    caller has no business learning that this id exists.
    """
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
