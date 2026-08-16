"""
scheduler/jobs.py

The job body behind cron.py's "check-due-schedules" beat entry: finds
every recurring Schedule (services/scheduler_service.py) whose
next_run_at has passed, fires an audit for it, and rolls next_run_at
forward — the exact same "create an Audit + bump last/next run" logic
services.scheduler_service.run_schedule_now uses for a manual "Run now"
click, just triggered by a clock instead of a request.

This intentionally duplicates a small amount of that function rather
than calling it directly: run_schedule_now takes a `user` (for its
404/ownership check) because it's answering a request on that user's
behalf, whereas this job is iterating *every* due schedule regardless of
whose it is — there's no "current user" here, so it fetches user_id
straight off the Schedule row instead.
"""

from datetime import datetime, timezone

from config.config import logger
from config.database import AsyncSessionLocal, run_async
from workers.celery_worker import celery_app


@celery_app.task(name="scheduler.jobs.check_due_schedules_task")
def check_due_schedules_task() -> dict:
    logger.info("[scheduler.jobs] checking for due schedules")
    result = run_async(_check_due_schedules_async())
    logger.info(f"[scheduler.jobs] dispatched {result['dispatched']} audit(s) from due schedules")
    return result


async def _check_due_schedules_async() -> dict:
    from sqlalchemy import select

    from models.history import HistoryEventType, log_event
    from services.audit_service import new_audit
    from services.scheduler_service import DEFAULT_RUN_NOW_MAX_PAGES, Schedule, compute_next_run
    from workers.audit_worker import run_audit_task

    now = datetime.now(timezone.utc)
    dispatched_audit_ids = []

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Schedule).where(
                Schedule.is_active.is_(True),
                Schedule.next_run_at.is_not(None),
                Schedule.next_run_at <= now,
            )
        )
        due_schedules = list(result.scalars().all())

        for schedule in due_schedules:
            audit = new_audit(
                schedule.user_id,
                schedule.website_id,
                schedule.url,
                schedule.depth,
                DEFAULT_RUN_NOW_MAX_PAGES,
                schedule.modules,
            )
            db.add(audit)
            await db.flush()

            schedule.last_run_at = now
            schedule.next_run_at = compute_next_run(schedule.frequency, schedule.last_run_at)

            await log_event(
                db,
                schedule.user_id,
                HistoryEventType.SCHEDULE_RUN,
                description=f"Ran scheduled audit for {schedule.url} ({schedule.frequency.lower()})",
                audit_id=audit.id,
            )

            dispatched_audit_ids.append(audit.id)

        await db.commit()

    for audit_id in dispatched_audit_ids:
        run_audit_task.delay(audit_id)

    return {"dispatched": len(dispatched_audit_ids), "audit_ids": dispatched_audit_ids}
