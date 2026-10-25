"""
Database models. Importing this package registers every table.
"""

from models.user import User
from models.website import Website, get_or_create_website, hostname_of, record_audit_result
from models.audit import Audit
from models.issue import Issue, IssueSeverity, IssueStatus, sync_issues_from_findings
from models.consent import Consent
from models.analytics import Analytics
from models.journey import Journey
from models.screenshot_blob import ScreenshotBlob
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
    "Journey",
    "ScreenshotBlob",
    "Report",
    "ReportEmail",
    "History",
    "HistoryEventType",
    "log_event",
]
