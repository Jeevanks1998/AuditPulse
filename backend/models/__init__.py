"""
models/

All SQLAlchemy ORM models for the AuditPulse backend, in one package so:

  1. `from models.audit import Audit` etc. gives every api/ router a
     single, obvious import path for schema/relationship definitions
     (business logic — routes, pipelines, query helpers — stays in api/).
  2. Importing `models` (as main.py does before `init_db()` runs) is
     enough to register every table on `Base.metadata`, so
     `Base.metadata.create_all` in config/database.py picks up the full
     schema regardless of which api/ modules happen to have been
     imported yet.

Import order matters a little for the TYPE_CHECKING-only relationship
strings to resolve at mapper-configuration time, but SQLAlchemy resolves
string relationship targets lazily against the shared registry, so any
order works as long as every module below has been imported once.
"""

from models.user import User
from models.website import Website, get_or_create_website, hostname_of, record_audit_result
from models.audit import Audit
from models.issue import Issue, IssueSeverity, IssueStatus, sync_issues_from_findings
from models.consent import Consent
from models.analytics import Analytics
from models.report import Report
from models.report_email import ReportEmail
from models.history import History, HistoryEventType, log_event

__all__ = [
    "User",
    "Website",
    "get_or_create_website",
    "hostname_of",
    "record_audit_result",
    "Audit",
    "Issue",
    "IssueSeverity",
    "IssueStatus",
    "sync_issues_from_findings",
    "Consent",
    "Analytics",
    "Report",
    "ReportEmail",
    "History",
    "HistoryEventType",
    "log_event",
]
