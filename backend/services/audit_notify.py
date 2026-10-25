"""
"Audit finished" email to the person who ran the audit, sent when it completes
or fails. Respects the Settings toggle "Audit completed" (notify_audit_completed).
Short plain text with a link to the report, no attachments. Never raises.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from config.constants import SCORE_BANDS
from config.database import AsyncSessionLocal
from config.logging import logger
from config.settings import settings


def frontend_url() -> str:
    """FRONTEND_URL, else the first https origin in CORS_ORIGINS_RAW, else ''."""
    if settings.FRONTEND_URL.strip():
        return settings.FRONTEND_URL.strip().rstrip("/")
    for origin in settings.CORS_ORIGINS:
        if origin.startswith("https://"):
            return origin.rstrip("/")
    return ""


def _band(score: Optional[int]) -> str:
    if score is None:
        return "Not scored"
    if score >= SCORE_BANDS["good"]:
        return "Healthy"
    if score >= SCORE_BANDS["mid"]:
        return "Needs attention"
    return "Issues found"


def _site(url: str) -> str:
    return urlparse(url).netloc or url


def build_message(audit, user_name: str, base_url: str) -> tuple[str, str]:
    """(subject, body) for a completed or failed audit."""
    from schemas.report import MODULE_LABELS

    site = _site(audit.url)
    name = (user_name or "").strip().split(" ")[0] or "there"
    link = f"{base_url}/report.html?id={audit.id}" if base_url else ""

    if audit.status != "completed":
        subject = f"Audit failed: {site}"
        lines = [
            f"Hi {name},",
            "",
            f"Your audit of {audit.url} could not finish.",
            f"Reason: {audit.error_message or 'unknown error'}",
            "",
            "You can run it again from the New Audit page.",
        ]
        if base_url:
            lines.append(f"{base_url}/audit.html")
        return subject, "\n".join(lines)

    score = audit.overall_score
    score_text = f"{score}/100" if score is not None else "not scored"
    subject = f"Audit complete: {site} scored {score_text}"

    findings = audit.findings or []
    critical = sum(1 for f in findings if f.get("severity") == "critical")
    warnings = sum(1 for f in findings if f.get("severity") == "warning")

    lines = [
        f"Hi {name},",
        "",
        f"Your audit of {audit.url} has finished.",
        "",
        f"Overall score: {score_text} ({_band(score)})" if score is not None else "Overall score: not scored",
    ]
    for module, value in (audit.breakdown or {}).items():
        label = MODULE_LABELS.get(module, module.replace("_", " ").title())
        lines.append(f"  {label}: {value}/100" if value is not None else f"  {label}: not scored")
    lines += ["", f"Issues: {critical} critical, {warnings} warnings"]
    if link:
        lines += ["", "Open the full report:", link]
    lines += ["", "You can turn these emails off in AuditPulse under Settings > Notifications."]
    return subject, "\n".join(lines)


async def notify_audit_finished(audit_id: int) -> Optional[str]:
    """Emails the audit owner. Returns "sent" / "failed", or None when nothing was sent."""
    try:
        from emailer.service import send_plain_email
        from models.audit import Audit
        from models.user import User

        if not settings.EMAIL_ENABLED:
            return None
        async with AsyncSessionLocal() as db:
            audit = await db.get(Audit, audit_id)
            if audit is None or audit.status not in ("completed", "failed"):
                return None
            user = await db.get(User, audit.user_id)
            if user is None or not user.is_active or not user.notify_audit_completed or not user.email:
                return None
            subject, body = build_message(audit, user.name, frontend_url())
            to = [user.email]

        outcome = await send_plain_email(to=to, subject=subject, body=body)
        if outcome.success:
            logger.info(f"Audit {audit_id}: 'audit finished' email sent")
        else:
            logger.warning(f"Audit {audit_id}: 'audit finished' email failed: {outcome.error_message}")
        return outcome.status
    except Exception:  # noqa: BLE001
        logger.exception(f"Audit {audit_id}: 'audit finished' email crashed")
        return "failed"
