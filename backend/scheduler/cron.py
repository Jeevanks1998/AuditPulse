"""
scheduler/cron.py

The beat schedule — *when* each periodic job runs. Kept separate from
the job bodies (jobs.py / reminders.py) and from the Celery app itself
(workers/celery_worker.py imports BEAT_SCHEDULE, never the other way
around, to avoid a circular import between the two modules).

Task names below (the string keys passed to `crontab`'s callers via
`task=`) must match the `name=` a task was registered under in
workers/audit_worker.py, scheduler/jobs.py, or scheduler/reminders.py —
Celery beat dispatches by name, not by importing the function.
"""

from celery.schedules import crontab

BEAT_SCHEDULE = {
    # ----------------------------------------------------------------
    # scheduler/jobs.py — fires any recurring Schedule (models in
    # services/scheduler_service.py) whose next_run_at has passed.
    # Every 5 minutes is granular enough for the Daily/Weekly/Monthly
    # cadences settings.html and the scheduler UI offer, without
    # hammering the DB with a tight poll loop.
    # ----------------------------------------------------------------
    "check-due-schedules": {
        "task": "scheduler.jobs.check_due_schedules_task",
        "schedule": crontab(minute="*/5"),
    },
    # ----------------------------------------------------------------
    # workers/audit_worker.py — safety net for audits a crashed/killed
    # worker left stuck in 'running'. Hourly is plenty; a genuinely
    # crawling audit finishes in well under 30 minutes (see
    # config.constants.AUDIT_STEPS), so anything still 'running' past
    # that threshold is dead, not slow.
    # ----------------------------------------------------------------
    "requeue-stuck-audits": {
        "task": "workers.audit_worker.requeue_stuck_audits_task",
        "schedule": crontab(minute=0),  # top of every hour
    },
    # ----------------------------------------------------------------
    # scheduler/reminders.py — settings.html's "Weekly summary" toggle
    # (User.notify_weekly_summary). Monday 7am UTC: after the "Weekly /
    # Mondays, 6:00 AM" default schedule cadence has had an hour to
    # produce a fresh audit to summarize.
    # ----------------------------------------------------------------
    "send-weekly-summaries": {
        "task": "scheduler.reminders.send_weekly_summaries_task",
        "schedule": crontab(minute=0, hour=7, day_of_week="monday"),
    },
}
