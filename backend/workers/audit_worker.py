"""
Celery tasks for audits. Each task is a small sync wrapper that runs its async
code in its own event loop with its own database session.
"""

import asyncio
from datetime import datetime, timezone

from config.config import logger
from config.database import AsyncSessionLocal
from workers.celery_worker import celery_app

# run_audit_task: runs one audit (same as the API's background task)
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
    """Runs one audit, retrying only if something outside the pipeline's own error handling failed."""
    logger.info(f"[audit_worker] starting audit {audit_id} (attempt {self.request.retries + 1})")
    try:
        asyncio.run(_run_audit_async(audit_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[audit_worker] audit {audit_id} task-level failure: {exc}")
        raise self.retry(exc=exc)
    return {"audit_id": audit_id, "status": "dispatched"}


async def _run_audit_async(audit_id: int) -> None:
    # Local import avoids a cycle at start-up.
    from services.audit_service import run_audit_pipeline

    await run_audit_pipeline(audit_id)

    # Then pre-build the report and send any critical-issue alert.
    from models.audit import Audit

    async with AsyncSessionLocal() as db:
        audit = await db.get(Audit, audit_id)
        if audit and audit.status == "completed":
            from workers.report_worker import warm_report_cache_task

            warm_report_cache_task.delay(audit_id)

            from scheduler.reminders import notify_critical_issues_task

            notify_critical_issues_task.delay(audit_id)


# requeue_stuck_audits_task: marks audits stuck in "running" by a crashed worker
@celery_app.task(name="workers.audit_worker.requeue_stuck_audits_task")
def requeue_stuck_audits_task(stuck_after_minutes: int = 60) -> dict:
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
            select(Audit).where(Audit.status == "running", Audit.started_at < cutoff, Audit.deleted_at.is_(None))
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
