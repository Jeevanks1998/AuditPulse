"""
scheduler/reminders.py

The two notification toggles settings.html exposes but nothing in the
API currently acts on: User.notify_weekly_summary ("Weekly summary" of
audit activity) and User.notify_critical_issue (alert as soon as an
audit turns up a critical finding). User.notify_audit_completed is left
alone here — that one fires per-audit, right when
services.audit_service.run_audit_pipeline finishes, so it belongs as a
follow-up next to workers.audit_worker's own completion handling rather
than a periodic job; see workers/audit_worker.py's docstring for where
that hook lives.

There's no SMTP/SendGrid/etc. integration anywhere else in this project
(see config/settings.py — no MAIL_* settings), so `_deliver` below is a
placeholder the same way services.audit_service's
`_write_consent_result` / `_write_analytics_result` are: it logs the
notification and records it on the user's activity feed (models/history)
so the *behavior* (who gets notified, when, with what content) is fully
wired up and testable, and swapping the delivery mechanism for a real
email provider later is a one-function change.
"""

import asyncio
from typing import Optional

from config.config import logger
from config.database import AsyncSessionLocal, run_async
from workers.celery_worker import celery_app

WEEKLY_SUMMARY_EVENT = "weekly_summary_sent"
CRITICAL_ISSUE_EVENT = "critical_issue_alert_sent"


# --------------------------------------------------------------------------
# Delivery placeholder
# --------------------------------------------------------------------------
async def _deliver(db, user, event_type: str, subject: str, body: str, audit_id: Optional[int] = None) -> None:
    """Stands in for a real email/push send. Logs the notification and
    appends a History row so it shows up on the account activity feed
    and is inspectable/testable without a mail server.
    """
    from models.history import log_event

    logger.info(f"[reminders] -> {user.email}: {subject}")
    logger.debug(f"[reminders] body for {user.email}: {body}")

    await log_event(db, user.id, event_type, description=subject, audit_id=audit_id, meta={"body": body})


# --------------------------------------------------------------------------
# Weekly summary — beat-scheduled (scheduler/cron.py: "send-weekly-summaries")
# --------------------------------------------------------------------------
@celery_app.task(name="scheduler.reminders.send_weekly_summaries_task")
def send_weekly_summaries_task() -> dict:
    logger.info("[reminders] sending weekly summaries")
    result = run_async(_send_weekly_summaries_async())
    logger.info(f"[reminders] sent {result['sent']} weekly summary/summaries")
    return result


async def _send_weekly_summaries_async() -> dict:
    from sqlalchemy import select

    from models.user import User
    from services.audit_service import compute_stats

    sent_user_ids = []

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.is_active.is_(True), User.notify_weekly_summary.is_(True))
        )
        users = list(result.scalars().all())

        for user in users:
            stats = await compute_stats(db, user)
            if stats.total_audits == 0:
                continue  # nothing to summarize yet

            subject = f"Your weekly AuditPulse summary — overall score {stats.overall}"
            body = (
                f"{stats.total_audits} total audit(s) tracked. "
                f"Latest overall score: {stats.overall}/100. "
                f"{stats.critical_issues} critical issue(s) outstanding across "
                f"{stats.seo_issues} SEO finding(s)."
            )
            await _deliver(db, user, WEEKLY_SUMMARY_EVENT, subject, body)
            sent_user_ids.append(user.id)

        await db.commit()

    return {"sent": len(sent_user_ids), "user_ids": sent_user_ids}


# --------------------------------------------------------------------------
# Critical issue alert — triggered right after an audit completes (see
# workers/audit_worker.py's post-pipeline hook), not on a timer.
# --------------------------------------------------------------------------
@celery_app.task(name="scheduler.reminders.notify_critical_issues_task")
def notify_critical_issues_task(audit_id: int) -> dict:
    result = run_async(_notify_critical_issues_async(audit_id))
    if result["notified"]:
        logger.info(f"[reminders] critical-issue alert sent for audit {audit_id}")
    return result


async def _notify_critical_issues_async(audit_id: int) -> dict:
    from models.audit import Audit
    from models.user import User

    async with AsyncSessionLocal() as db:
        audit = await db.get(Audit, audit_id)
        if not audit or audit.status != "completed":
            return {"notified": False}

        critical_findings = [f for f in (audit.findings or []) if f.get("severity") == "critical"]
        if not critical_findings:
            return {"notified": False}

        user = await db.get(User, audit.user_id)
        if not user or not user.is_active or not user.notify_critical_issue:
            return {"notified": False}

        subject = f"{len(critical_findings)} critical issue(s) found on {audit.url}"
        body = "; ".join(f.get("title", "Untitled finding") for f in critical_findings[:5])

        await _deliver(db, user, CRITICAL_ISSUE_EVENT, subject, body, audit_id=audit.id)
        await db.commit()

    return {"notified": True, "count": len(critical_findings)}
