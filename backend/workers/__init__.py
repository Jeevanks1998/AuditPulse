"""
workers/

Celery entry point + task definitions. The rest of the app already runs
audits inline via FastAPI BackgroundTasks (see services.audit_service.
run_audit_pipeline, called from api/audit.py and api/scheduler.py) — that
works for a single dev process, but doesn't survive a process restart,
can't be retried, and doesn't scale past one machine.

This package puts the same pipeline behind real Celery tasks so it can
run in a separate worker process (or fleet of processes), with retries,
and be triggered either from the API (swap BackgroundTasks for a
`.delay()` call) or from scheduler/ (recurring jobs via Celery beat).

  celery_worker.py - the Celery app itself: broker/backend config, task
                      autodiscovery, beat schedule wiring
  audit_worker.py  - tasks that run/retry the audit pipeline
  report_worker.py - tasks that pre-generate/cache report exports
                      (JSON/HTML/PDF) once an audit finishes

Nothing here imports from api/ — routers may call into these tasks
(`.delay(...)`), never the other way around, same rule as services/.
"""
