"""
emailer/templates.py

Builds the "Send to POC" email's default subject/body. The body template
uses {{token}} merge fields — the same six fields and the same syntax as
the composer's default message in assets/js/email-composer.js
(EMAIL_BODY_TEMPLATE/fillEmailTemplate) — so the wording matches whether
it's generated here (the fallback used when a send request omits `body`)
or on the frontend (what the user actually sees and can edit before
sending). Keep the two in sync if this template changes.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from reports.generator import ReportPayload

_TEMPLATE = """Hi {{poc_name}},

Please find attached the latest AuditPulse website audit report for {{website_name}}.

Audit Date: {{audit_date}}
Report ID: {{report_id}}
Overall Score: {{overall_score}}/100
Overall Status: {{overall_status}}

The detailed report and supporting evidence are attached for your review.

Please let us know if any clarification is required.

Regards,
AuditPulse"""

_TOKEN_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def render_template(template: str, values: dict) -> str:
    """Fills {{token}} merge fields; a token with no value in `values` is left as-is."""

    def _sub(match: "re.Match[str]") -> str:
        val = values.get(match.group(1))
        return match.group(0) if val in (None, "") else str(val)

    return _TOKEN_RE.sub(_sub, template)


def _hostname(url: str) -> str:
    """example.com from any of https://example.com/path, http://www.x.com, or a bare host."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else "https://" + raw)
    host = parsed.hostname or raw
    return host[4:] if host.startswith("www.") else host


def _subject_date(generated_at: str) -> str:
    """'19 Sep 2026' — matches assets/js/email-composer.js's formatSubjectDate()."""
    if not generated_at:
        return ""
    try:
        dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return dt.strftime("%d %b %Y")


def build_subject(payload: ReportPayload) -> str:
    host = _hostname(payload.url)
    when = _subject_date(payload.generated_at)
    subject = f"AuditPulse | Website Audit Report – {host}"
    return f"{subject} | {when}" if when else subject


def build_body(payload: ReportPayload, *, poc_name: str = "there") -> str:
    return render_template(_TEMPLATE, {
        "poc_name": poc_name or "there",
        "website_name": payload.url,
        "audit_date": (payload.generated_at or "")[:10] or "—",
        "report_id": payload.audit_id,
        "overall_score": payload.overall,
        "overall_status": payload.overall_status or "—",
    })
