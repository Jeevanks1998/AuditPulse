"""
services/

Business logic for the AuditPulse backend, in one package so api/
routers stay thin (parse the request, call a service, shape the
response) and every non-trivial operation — the audit pipeline, report
shaping, dashboard aggregation, history queries, schedules, AI-module
findings — lives in exactly one place, independent of FastAPI.

Layering: api/ -> services/ -> models/ + schemas/. Modules in this
package never import from api/, so nothing here depends on a request
being in flight; that's what keeps `services.audit_service.run_audit_pipeline`
safely callable from a BackgroundTasks callback (or, eventually, a
Celery worker) with its own DB session.

  * audit_service     — create/query audits, stats, and the pipeline
  * report_service     — shape a completed audit into a report, share/export
  * dashboard_service   — aggregate stats + recent audits for dashboard.html
  * history_service     — audit-run history + account activity feed
  * scheduler_service   — recurring audit schedules (owns the Schedule model)
  * ai_service          — the "ai" audit module's provider call + fallback
"""
