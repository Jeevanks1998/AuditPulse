"""
Report endpoints: views, exports, share links and email. Logic lives in services.report_service.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import User, get_current_user
from config.database import get_db
from schemas.email import (
    EmailHistoryOut,
    EmailHistoryPage,
    EmailSendRequest,
    EmailSendResult,
)
from schemas.report import ReportOut, ShareOut
from services import report_service

router = APIRouter()


# Email history (account-wide). These fixed paths are declared before the
# "/{audit_id}" routes so they are matched first.
@router.get("/email/attachment-choices")
async def get_email_attachment_choices(current_user: User = Depends(get_current_user)):
    """Attachment options for the "Send to POC" dialog."""
    return report_service.get_attachment_choices()


@router.get("/email/history", response_model=EmailHistoryPage)
async def list_email_history(
    q: Optional[str] = None,
    status: Optional[str] = Query(None, pattern="^(sent|failed)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every send for this account, newest first, plus totals for the stat cards."""
    return await report_service.list_email_history(
        db, current_user, q=q, status_filter=status, page=page, page_size=page_size
    )


@router.get("/email/history/{email_id}", response_model=EmailHistoryOut)
async def get_email_record(
    email_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One sent email in full (for View and Resend). 404 if it isn't yours."""
    return await report_service.get_email_record(email_id, db, current_user)


@router.get("/{audit_id}", response_model=ReportOut)
async def get_report(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await report_service.get_report(audit_id, db, current_user)


@router.post("/{audit_id}/share", response_model=ShareOut)
async def share_report(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await report_service.share_report(audit_id, db, current_user)


@router.get("/{audit_id}/export")
async def export_report_pdf(
    audit_id: int,
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full report as a PDF."""
    pdf_bytes = await report_service.export_report_pdf(audit_id, db, current_user, force_refresh=refresh)
    headers = {"Content-Disposition": f'attachment; filename="audit-{audit_id}-report.pdf"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get("/{audit_id}/export.json")
async def export_report_json(
    audit_id: int,
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full report as JSON (scores, findings and AI sections)."""
    data = await report_service.export_report_json(audit_id, db, current_user, force_refresh=refresh)
    return JSONResponse(content=data)


@router.get("/{audit_id}/export.html", response_class=HTMLResponse)
async def export_report_html(
    audit_id: int,
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full report as one self-contained HTML file."""
    html = await report_service.export_report_html(audit_id, db, current_user, force_refresh=refresh)
    return HTMLResponse(content=html)


@router.get("/{audit_id}/evidence.zip")
async def export_evidence_zip(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Evidence ZIP: PDF, screenshots and cookie/network JSON."""
    zip_bytes, filename = await report_service.export_evidence_zip(audit_id, db, current_user)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=zip_bytes, media_type="application/zip", headers=headers)


@router.post("/{audit_id}/send", response_model=EmailSendResult)
async def send_report_to_poc(
    audit_id: int,
    request: EmailSendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Emails the report to POC recipients and records it in Email History."""
    return await report_service.send_report_to_poc(audit_id, request, db, current_user)


@router.get("/{audit_id}/email-history", response_model=List[EmailHistoryOut])
async def get_email_history(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every "Send to POC" attempt for this audit, newest first."""
    return await report_service.get_email_history(audit_id, db, current_user)
