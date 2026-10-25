"""
Business logic. api/ routers stay thin and call these; nothing here imports api/.
  audit_service     - create and query audits, and the audit pipeline
  report_service    - reports, sharing, exports and email
  dashboard_service - dashboard stats and recent audits
  history_service   - audit history and activity feed
  scheduler_service - recurring schedules
  ai_service        - AI findings and the AI report panel
"""
