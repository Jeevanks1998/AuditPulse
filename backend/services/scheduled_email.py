"""
services/scheduled_email.py

Automatic report delivery for scheduled audits. A schedule can carry an
`email_delivery` config (recipients + which reports to attach, set in the
Schedule an Audit dialog). When an audit fired by that schedule finishes,
audit_service.run_audit_pipeline calls `deliver_scheduled_report`, which
sends the report through the same path as the report page's "Send to POC"
button (services.report_service.send_report_to_poc) — so the send shows
up on the Email Reports page and in History like any manual send — and
records the outcome back on the schedule for the Scheduler table.

Never raises: a delivery problem must not turn a finished audit into a
failed one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from config.database import AsyncSessionLocal
from config.logging import logger


def _clean_list(values) -> list:
    return [str(v).strip() for v in (values or []) if str(v).strip()]


async def deliver_scheduled_report(audit_id: int) -> Optional[str]:
    """Email the finished audit's report to its schedule's recipients.

    Returns "sent" / "failed", or None when there was nothing to send (not
    a scheduled audit, delivery switched off, no recipients, audit not
    completed)."""
    try:
        return await _deliver(audit_id)
    except Exception:  # noqa: BLE001
        logger.exception(f"Audit {audit_id}: scheduled report email crashed")
        return "failed"


async def _deliver(audit_id: int) -> Optional[str]:
    from pydantic import ValidationError

    from models.audit import Audit
    from models.user import User
    from schemas.email import EmailSendRequest
    from services import report_service
    from services.scheduler_service import Schedule

    async with AsyncSessionLocal() as db:
        audit = await db.get(Audit, audit_id)
        if audit is None or not audit.schedule_id or audit.status != "completed":
            return None
        schedule = await db.get(Schedule, audit.schedule_id)
        if schedule is None or schedule.user_id != audit.user_id:
            return None
        cfg = dict(schedule.email_delivery or {})
        to = _clean_list(cfg.get("to"))
        if not cfg.get("enabled") or not to:
            return None
        user = await db.get(User, audit.user_id)
        if user is None:
            return None

        schedule_id = schedule.id
        url = audit.url
        try:
            request = EmailSendRequest(
                to=to,
                cc=_clean_list(cfg.get("cc")),
                subject=(cfg.get("subject") or "").strip() or None,
                attachments=cfg.get("attachments") or ["pdf"],
            )
        except ValidationError as exc:
            result_status, error = "failed", f"Invalid email settings: {exc.errors()[0].get('msg')}"
        else:
            logger.info(f"Audit {audit_id}: emailing scheduled report for {url} to {', '.join(to)}")
            result = await report_service.send_report_to_poc(
                audit_id, request, db, user, body_intro=(cfg.get("message") or "").strip() or None
            )
            result_status, error = result.status, result.error_message

    # Record the outcome on the schedule in a fresh session: send_report_to_poc
    # has already committed (and expired) everything in the one above.
    async with AsyncSessionLocal() as db:
        schedule = await db.get(Schedule, schedule_id)
        if schedule is not None:
            cfg = dict(schedule.email_delivery or {})
            cfg.update(
                last_status=result_status,
                last_sent_at=datetime.now(timezone.utc).isoformat(),
                last_error=(error or None) and str(error)[:300],
                last_audit_id=audit_id,
            )
            schedule.email_delivery = cfg  # reassign: plain JSON columns don't track in-place edits
            await db.commit()

    if result_status == "sent":
        logger.info(f"Audit {audit_id}: scheduled report emailed")
    else:
        logger.warning(f"Audit {audit_id}: scheduled report email failed — {error}")
    return result_status
