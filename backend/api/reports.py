"""
api/reports.py

Read-only report views for report.html. Parses requests and shapes
responses only — building the score grid, resolving/minting share
tokens, and the export placeholder all live in services.report_service.
"""

from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import User, get_current_user
from config.database import get_db
from schemas.email import EmailHistoryOut, EmailSendRequest, EmailSendResult
from schemas.report import ReportOut, ShareOut
from services import report_service

router = APIRouter()


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
    """Full report export as a single PDF document (see pdf/pdf_generator.py)."""
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
    """Full report export (score grid, findings, AI summary/priorities/business-impact/action-plan) as JSON."""
    data = await report_service.export_report_json(audit_id, db, current_user, force_refresh=refresh)
    return JSONResponse(content=data)


@router.get("/{audit_id}/export.html", response_class=HTMLResponse)
async def export_report_html(
    audit_id: int,
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full report export as a single self-contained HTML document (see reports/html_report.py)."""
    html = await report_service.export_report_html(audit_id, db, current_user, force_refresh=refresh)
    return HTMLResponse(content=html)


@router.get("/{audit_id}/evidence.zip")
async def export_evidence_zip(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Complete evidence package as a single ZIP download (§5.2) — PDF + screenshots + cookie/network JSON."""
    zip_bytes, filename = await report_service.export_evidence_zip(audit_id, db, current_user)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=zip_bytes, media_type="application/zip", headers=headers)


@router.get("/email/attachment-choices")
async def get_email_attachment_choices(current_user: User = Depends(get_current_user)):
    """Checkbox options for the "Send to POC" modal's attachment picker (§9.2)."""
    return report_service.get_attachment_choices()


@router.post("/{audit_id}/send", response_model=EmailSendResult)
async def send_report_to_poc(
    audit_id: int,
    request: EmailSendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sends the report to one or more POC recipients (§9.1) and logs the attempt in Email History (§10)."""
    return await report_service.send_report_to_poc(audit_id, request, db, current_user)


@router.get("/{audit_id}/email-history", response_model=List[EmailHistoryOut])
async def get_email_history(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every "Send to POC" attempt for this audit, most recent first (§10)."""
    return await report_service.get_email_history(audit_id, db, current_user)
