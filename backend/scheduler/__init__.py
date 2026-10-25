"""
Timed jobs run by Celery beat:
  cron.py      - which job runs when (BEAT_SCHEDULE)
  jobs.py      - starts audits for schedules that are due
  reminders.py - weekly summaries and critical-issue alerts
"""
