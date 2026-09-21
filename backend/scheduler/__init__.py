"""
scheduler/

Periodic (Celery beat) execution. services/scheduler_service.py already
owns the CRUD for recurring audit `Schedule` rows (settings.html's
frequency/time fields, plus per-URL schedules on scheduler-related API
routes) and can trigger one on demand — but, as its own docstring notes,
it stops short of *actually* firing schedules on a timer, since that's a
beat-worker concern, not a request-handling one.

This package is that beat worker's job list:

  cron.py      - the BEAT_SCHEDULE dict (which job, how often) consumed
                 by workers/celery_worker.py
  jobs.py      - polls Schedule rows for ones whose next_run_at has
                 passed and dispatches an audit for each
  reminders.py - user-facing notification jobs (weekly summary,
                 critical-issue alerts) — the "why would I get an email
                 from this" half of the scheduler, as opposed to jobs.py's
                 "why would an audit just start running" half

Like workers/, nothing here imports from api/ — the API only ever reads
Schedule rows or triggers one manually via services.scheduler_service;
it never imports these task modules directly.
"""
