"""
workers/report_worker.py

Celery tasks that build and cache the JSON/HTML/PDF report exports
(reports/, pdf/pdf_generator.py, reports/report_storage.py) ahead of
time, so the first click on report.html's "Export PDF" button doesn't
have to pay for the AI pipeline (reports.generator) and chart/PDF
rendering synchronously inside a request.

services.report_service.export_report_* already do the "check the
on-disk cache, rebuild + save if missing" dance for the API request
path, but they're written against a request-scoped `user` (for the
404/409 ownership + status checks). These tasks run outside any request,
so they talk to reports.* / pdf.pdf_generator / reports.report_storage
directly against the Audit row instead of going through report_service —
same underlying pipeline, no HTTPException-shaped detour.
"""

import asyncio
from typing import Optional

from config.config import logger
from config.database import AsyncSessionLocal
from workers.celery_worker import celery_app


@celery_app.task(
    name="workers.report_worker.warm_report_cache_task",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
    autoretry_for=(Exception,),
)
def warm_report_cache_task(self, audit_id: int) -> dict:
    """Pre-builds and caches JSON + HTML for a just-completed audit.

    PDF is deliberately left out of the automatic warm-up — it's the
    heaviest of the three (screenshot capture + chart rendering) and
    plenty of users never download it, so it's built on-demand by
    generate_report_pdf_task instead (called from api/reports.py's PDF
    endpoint the same way audits are dispatched to run_audit_task).
    """
    logger.info(f"[report_worker] warming report cache for audit {audit_id}")
    try:
        built = asyncio.run(_warm_report_cache_async(audit_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[report_worker] failed to warm cache for audit {audit_id}: {exc}")
        raise self.retry(exc=exc)
    return {"audit_id": audit_id, **built}


async def _warm_report_cache_async(audit_id: int) -> dict:
    from models.audit import Audit
    from reports import build_report_payload, render_html_report, to_json_report
    from reports.report_storage import save_html, save_json

    async with AsyncSessionLocal() as db:
        audit = await db.get(Audit, audit_id)
        if not audit or audit.status != "completed":
            logger.warning(f"[report_worker] audit {audit_id} not found or not completed — skipping")
            return {"json": False, "html": False}

        payload = await build_report_payload(
            audit_id=audit.id,
            url=audit.url,
            overall=audit.overall_score or 0,
            generated_at=audit.completed_at.isoformat() if audit.completed_at else "",
            breakdown=audit.breakdown or {},
            findings=audit.findings or [],
            share_url=None,
        )

    save_json(audit_id, to_json_report(payload))
    save_html(audit_id, render_html_report(payload))
    return {"json": True, "html": True}


@celery_app.task(
    name="workers.report_worker.generate_report_pdf_task",
    bind=True,
    max_retries=2,
    default_retry_delay=20,
    autoretry_for=(Exception,),
)
def generate_report_pdf_task(self, audit_id: int) -> dict:
    """Builds + caches the PDF export for one audit. Safe to call whether
    or not a cached copy already exists — it's a no-op cost-wise for the
    caller either way, since api/reports.py's own endpoint checks the
    cache first and only enqueues this when it's missing.
    """
    logger.info(f"[report_worker] generating PDF for audit {audit_id}")
    try:
        path = asyncio.run(_generate_report_pdf_async(audit_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[report_worker] failed to generate PDF for audit {audit_id}: {exc}")
        raise self.retry(exc=exc)
    return {"audit_id": audit_id, "path": path}


async def _generate_report_pdf_async(audit_id: int) -> Optional[str]:
    from crawler.screenshots import capture_screenshot
    from config.settings import settings
    from models.audit import Audit
    from pdf.pdf_generator import generate_pdf_report
    from reports import build_report_payload
    from reports.report_storage import save_pdf

    async with AsyncSessionLocal() as db:
        audit = await db.get(Audit, audit_id)
        if not audit or audit.status != "completed":
            logger.warning(f"[report_worker] audit {audit_id} not found or not completed — skipping PDF")
            return None

        payload = await build_report_payload(
            audit_id=audit.id,
            url=audit.url,
            overall=audit.overall_score or 0,
            generated_at=audit.completed_at.isoformat() if audit.completed_at else "",
            breakdown=audit.breakdown or {},
            findings=audit.findings or [],
            share_url=None,
        )

        screenshot_path = None
        if settings.CRAWLER_ENABLE_SCREENSHOTS:
            screenshot_path = await capture_screenshot(audit.url, filename_hint=f"audit-{audit.id}")

    pdf_bytes = generate_pdf_report(payload, screenshot_path=screenshot_path)
    return save_pdf(audit_id, pdf_bytes)
