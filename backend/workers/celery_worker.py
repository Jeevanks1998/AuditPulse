"""
The Celery app. Run with:

    celery -A workers.celery_worker worker --loglevel=info
    celery -A workers.celery_worker beat --loglevel=info

Uses CELERY_BROKER_URL / CELERY_RESULT_BACKEND from settings.
"""

from celery import Celery
from celery.schedules import crontab

from config.config import logger, settings

# App
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

# Settings
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Don't lose long tasks: re-queue them if a worker dies.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Separate queues so report exports can't hold up audits (and the other way round).
    task_routes={
        "workers.audit_worker.*": {"queue": "audits"},
        "workers.report_worker.*": {"queue": "reports"},
        "scheduler.jobs.*": {"queue": "default"},
        "scheduler.reminders.*": {"queue": "default"},
    },
    task_default_queue="default",
    result_expires=60 * 60 * 24,  # 1 day
)

# Timed jobs (defined in scheduler/cron.py)
from scheduler.cron import BEAT_SCHEDULE  # noqa: E402  (after celery_app exists)

celery_app.conf.beat_schedule = BEAT_SCHEDULE

logger.info(
    f"Celery app '{celery_app.main}' configured — broker={settings.CELERY_BROKER_URL}, "
    f"{len(BEAT_SCHEDULE)} beat job(s) registered"
)

# Re-export crontab for scheduler/cron.py.
__all__ = ["celery_app", "crontab"]
