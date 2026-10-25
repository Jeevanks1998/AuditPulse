"""
When each timed job runs. Task names must match the name= each task is
registered with (Celery beat starts tasks by name).
"""

from celery.schedules import crontab

BEAT_SCHEDULE = {
    # Start audits for due schedules, every 5 minutes.
    "check-due-schedules": {
        "task": "scheduler.jobs.check_due_schedules_task",
        "schedule": crontab(minute="*/5"),
    },
    # Every hour: fix audits a crashed worker left stuck in "running".
    "requeue-stuck-audits": {
        "task": "workers.audit_worker.requeue_stuck_audits_task",
        "schedule": crontab(minute=0),  # top of every hour
    },
    # Weekly summary email, Mondays 7:00 UTC.
    "send-weekly-summaries": {
        "task": "scheduler.reminders.send_weekly_summaries_task",
        "schedule": crontab(minute=0, hour=7, day_of_week="monday"),
    },
}
