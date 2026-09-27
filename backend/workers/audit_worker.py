"""
workers/audit_worker.py

Celery tasks wrapping services.audit_service — the same pipeline
api/audit.py currently fires with FastAPI BackgroundTasks, now runnable
out-of-process with retries and visibility.

Celery tasks are synchronous by definition (the worker calls the
function directly, no event loop of its own), but the whole app is
async SQLAlchemy end to end, so every task here follows one pattern:
a thin sync `@celery_app.task` wrapper that does nothing but
`asyncio.run(...)` an `async def _*_async(...)` implementation. Each
task run gets its own event loop and, inside that, its own DB session
via config.database.AsyncSessionLocal — never a request-scoped session,
since none exists here.
"""

import asyncio
from datetime import datetime, timezone

from config.config import logger
from config.database import AsyncSessionLocal
from workers.celery_worker import celery_app

# --------------------------------------------------------------------------
# run_audit_task — the main entry point. Same job api/audit.py's
# BackgroundTasks call does today (services.audit_service.run_audit_pipeline);
# swapping `background_tasks.add_task(...)` for
# `workers.audit_worker.run_audit_task.delay(audit.id)` is a one-line change
# once a worker process is actually running.
# --------------------------------------------------------------------------
@celery_app.task(
    name="workers.audit_worker.run_audit_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,  # seconds
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def run_audit_task(self, audit_id: int) -> dict:
    """Runs one audit end to end. Retries on unexpected failure (network
    blips, transient DB errors); services.audit_service.run_audit_pipeline
    already catches per-audit exceptions and marks the row 'failed', so a
    retry here only fires if something *outside* that try/except blew up
    (e.g. the DB was unreachable at task start).
    """
    logger.info(f"[audit_worker] starting audit {audit_id} (attempt {self.request.retries + 1})")
    try:
        asyncio.run(_run_audit_async(audit_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[audit_worker] audit {audit_id} task-level failure: {exc}")
        raise self.retry(exc=exc)
    return {"audit_id": audit_id, "status": "dispatched"}


async def _run_audit_async(audit_id: int) -> None:
    # Local import avoids a module import cycle at worker start-up
    # (services.audit_service pulls in services.ai_service, models, etc.)
    from services.audit_service import run_audit_pipeline

    await run_audit_pipeline(audit_id)

    # Chain a best-effort report pre-warm + reminder check once the audit
    # is done, so the PDF/JSON are already cached and the user gets a
    # critical-issue nudge without waiting on the next beat tick.
    from models.audit import Audit

    async with AsyncSessionLocal() as db:
        audit = await db.get(Audit, audit_id)
        if audit and audit.status == "completed":
            from workers.report_worker import warm_report_cache_task

            warm_report_cache_task.delay(audit_id)

            from scheduler.reminders import notify_critical_issues_task

            notify_critical_issues_task.delay(audit_id)


# --------------------------------------------------------------------------
# requeue_stuck_audits_task — periodic safety net (wired into
# scheduler/cron.py's beat schedule). Catches audits left in 'running' by a
# worker that died mid-pipeline (no exception was ever persisted, so the row
# just sits there forever otherwise).
# --------------------------------------------------------------------------
@celery_app.task(name="workers.audit_worker.requeue_stuck_audits_task")
def requeue_stuck_audits_task(stuck_after_minutes: int = 30) -> dict:
    logger.info("[audit_worker] scanning for stuck audits")
    result = asyncio.run(_requeue_stuck_audits_async(stuck_after_minutes))
    logger.info(f"[audit_worker] requeued {result['requeued']} stuck audit(s)")
    return result


async def _requeue_stuck_audits_async(stuck_after_minutes: int) -> dict:
    from datetime import timedelta

    from sqlalchemy import select

    from models.audit import Audit

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stuck_after_minutes)
    requeued_ids = []

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Audit).where(Audit.status == "running", Audit.started_at < cutoff)
        )
        stuck = list(result.scalars().all())

        for audit in stuck:
            audit.status = "queued"
            audit.current_step = None
            audit.percent = 0
            audit.error_message = "Requeued after worker timeout"
            requeued_ids.append(audit.id)

        await db.commit()

    for audit_id in requeued_ids:
        run_audit_task.delay(audit_id)

    return {"requeued": len(requeued_ids), "audit_ids": requeued_ids}
