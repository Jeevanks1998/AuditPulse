"""
workers/celery_worker.py

The Celery application instance for AuditPulse. This is the module you
point the `celery` CLI at:

    # worker process (runs tasks)
    celery -A workers.celery_worker worker --loglevel=info

    # beat process (fires scheduler/cron.py's periodic jobs on time)
    celery -A workers.celery_worker beat --loglevel=info

    # or both in one process (dev only — never in production)
    celery -A workers.celery_worker worker --beat --loglevel=info

Broker/result backend reuse the same Redis settings the rest of the app
already has in config.settings (CELERY_BROKER_URL / CELERY_RESULT_BACKEND),
so there's exactly one place that configures Redis.

Task discovery is explicit rather than `autodiscover_tasks()` scanning
every installed app, since this project isn't a Django-style app
registry — we just import the handful of modules that define tasks.
"""

from celery import Celery
from celery.schedules import crontab

from config.config import logger, settings

# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
celery_app = Celery(
    "auditpulse",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "workers.audit_worker",
        "workers.report_worker",
        "scheduler.jobs",
        "scheduler.reminders",
    ],
)

# --------------------------------------------------------------------------
# Core config
# --------------------------------------------------------------------------
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Long-running crawls shouldn't be silently dropped by a broker visibility
    # timeout shorter than the audit itself; acks_late + reject_on_worker_lost
    # means a crashed worker re-queues the task instead of losing it.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Route the CPU/IO-bound audit pipeline and the PDF/report generation
    # onto their own queues so a burst of report exports can't starve
    # audits (or vice versa). scheduler jobs run on the default queue.
    task_routes={
        "workers.audit_worker.*": {"queue": "audits"},
        "workers.report_worker.*": {"queue": "reports"},
        "scheduler.jobs.*": {"queue": "default"},
        "scheduler.reminders.*": {"queue": "default"},
    },
    task_default_queue="default",
    result_expires=60 * 60 * 24,  # 1 day — plenty for polling a task's status
)

# --------------------------------------------------------------------------
# Beat schedule — periodic jobs, defined in scheduler/cron.py so the
# "when" (this file) stays separate from the "what" (scheduler/jobs.py,
# scheduler/reminders.py).
# --------------------------------------------------------------------------
from scheduler.cron import BEAT_SCHEDULE  # noqa: E402  (after celery_app exists)

celery_app.conf.beat_schedule = BEAT_SCHEDULE

logger.info(
    f"Celery app '{celery_app.main}' configured — broker={settings.CELERY_BROKER_URL}, "
    f"{len(BEAT_SCHEDULE)} beat job(s) registered"
)

# Re-export crontab so scheduler/cron.py has one obvious import path
# (`from workers.celery_worker import crontab`) without reaching into
# celery.schedules directly in more than one place.
__all__ = ["celery_app", "crontab"]
