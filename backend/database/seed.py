"""
database/seed.py

Idempotent dev-data seed script. Run after `alembic upgrade head` (or,
for a throwaway local DB, after main.py's own `init_db()` create_all)
against an empty-ish database to get a demo account with enough data to
exercise every screen (dashboard.html, audit.html, history.html,
report.html) without running a real crawl first.

Usage:
    python -m database.seed
    python -m database.seed --reset      # wipe seeded rows first
    python -m database.seed --email demo@example.com --password demo1234

Safe to re-run: looks up the demo user by email and skips creating it
(and its websites) again if it already exists, so this can sit in a
setup script or CI fixture step without accumulating duplicate rows.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

from passlib.context import CryptContext
from sqlalchemy import select

from config.logging import logger, setup_logging
from database.session import session_scope

# Imports the whole models/ package (not just the four modules used
# directly below) so every table is registered on Base.metadata and
# every relationship string (e.g. User.reports -> "Report") resolves
# once SQLAlchemy configures its mappers -- same reason main.py does
# `import models` before calling init_db(). Importing only
# models.audit/history/issue/user/website here would leave
# models.report/consent/analytics unregistered and break mapper
# configuration the first time any query runs.
import models  # noqa: F401
from models.audit import Audit
from models.history import HistoryEventType, log_event
from models.issue import sync_issues_from_findings
from models.user import User
from models.website import Website, hostname_of, record_audit_result

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEMO_EMAIL_DEFAULT = "demo@auditpulse.example.com"
DEMO_PASSWORD_DEFAULT = "DemoPass123!"

_SAMPLE_SITE_URL = "https://www.example.com"
_SAMPLE_BREAKDOWN = {
    "seo": 82,
    "performance": 68,
    "accessibility": 74,
    "security": 91,
}
_SAMPLE_FINDINGS = [
    {
        "module": "seo",
        "severity": "warning",
        "title": "Missing meta description",
        "description": "3 pages have no <meta name=\"description\"> tag.",
    },
    {
        "module": "performance",
        "severity": "critical",
        "title": "Unoptimized hero image",
        "description": "The homepage hero image is 4.2MB and not lazy-loaded.",
    },
    {
        "module": "accessibility",
        "severity": "warning",
        "title": "Low contrast body text",
        "description": "Body copy on a light-gray background falls below WCAG AA contrast.",
    },
    {
        "module": "security",
        "severity": "info",
        "title": "Missing Content-Security-Policy header",
        "description": "No CSP header was found on the homepage response.",
    },
]


async def _get_or_create_demo_user(db, email: str, password: str) -> tuple[User, bool]:
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        return existing, False

    user = User(
        name="Demo User",
        email=email,
        hashed_password=pwd_context.hash(password),
        company="AuditPulse Demo Co.",
        api_key=secrets.token_hex(24),
    )
    db.add(user)
    await db.flush()  # populate user.id for the rows below
    return user, True


async def _seed_website_and_audits(db, user: User) -> None:
    host = hostname_of(_SAMPLE_SITE_URL)
    website = Website(user_id=user.id, url=_SAMPLE_SITE_URL, hostname=host, is_monitored=True)
    db.add(website)
    await db.flush()

    now = datetime.now(timezone.utc)
    overall_score = round(sum(_SAMPLE_BREAKDOWN.values()) / len(_SAMPLE_BREAKDOWN))

    completed_audit = Audit(
        user_id=user.id,
        website_id=website.id,
        url=_SAMPLE_SITE_URL,
        label="Full site",
        depth="full",
        modules=list(_SAMPLE_BREAKDOWN.keys()),
        status="completed",
        current_step=None,
        percent=100,
        overall_score=overall_score,
        breakdown=_SAMPLE_BREAKDOWN,
        findings=_SAMPLE_FINDINGS,
        created_at=now - timedelta(days=2),
        started_at=now - timedelta(days=2),
        completed_at=now - timedelta(days=2) + timedelta(minutes=4),
    )
    # `issues` starts empty for a brand-new Audit; setting it explicitly
    # (rather than leaving the relationship unloaded) means
    # sync_issues_from_findings's `list(audit.issues)` reads the
    # already-loaded empty list instead of lazy-loading it — lazy-loads
    # aren't awaitable mid-coroutine on an AsyncSession and raise
    # MissingGreenlet.
    completed_audit.issues = []
    db.add(completed_audit)
    await db.flush()

    await sync_issues_from_findings(db, completed_audit, _SAMPLE_FINDINGS)
    await record_audit_result(website, overall_score, completed_audit.completed_at)

    queued_audit = Audit(
        user_id=user.id,
        website_id=website.id,
        url=_SAMPLE_SITE_URL + "/pricing",
        label="Homepage",
        depth="homepage",
        modules=["seo", "performance"],
        status="queued",
        percent=0,
        created_at=now,
    )
    db.add(queued_audit)

    await log_event(
        db,
        user_id=user.id,
        event_type=HistoryEventType.AUDIT_COMPLETED,
        description=f"Audit of {host} completed with a score of {overall_score}.",
        audit_id=completed_audit.id,
    )
    await log_event(
        db,
        user_id=user.id,
        event_type=HistoryEventType.AUDIT_CREATED,
        description=f"Audit queued for {host}/pricing.",
        audit_id=queued_audit.id,
    )


async def _reset(db, email: str) -> None:
    """Deletes the demo user (and, via cascade, everything owned by it)."""
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        return
    await db.delete(user)
    await db.flush()
    logger.info(f"seed: removed existing demo user {email!r} before reseeding")


async def run(email: str, password: str, reset: bool) -> None:
    async with session_scope() as db:
        if reset:
            await _reset(db, email)

        user, created = await _get_or_create_demo_user(db, email, password)
        if not created:
            logger.info(f"seed: demo user {email!r} already exists — skipping (use --reset to reseed)")
            return

        await log_event(db, user_id=user.id, event_type=HistoryEventType.REGISTER, description="Demo account created by seed script.")
        await _seed_website_and_audits(db, user)

    logger.info(f"seed: demo user ready -> email={email!r} password={password!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the AuditPulse database with demo data.")
    parser.add_argument("--email", default=DEMO_EMAIL_DEFAULT, help="Demo user email")
    parser.add_argument("--password", default=DEMO_PASSWORD_DEFAULT, help="Demo user password")
    parser.add_argument("--reset", action="store_true", help="Delete the demo user (and its data) before reseeding")
    args = parser.parse_args()

    setup_logging()
    asyncio.run(run(args.email, args.password, args.reset))


if __name__ == "__main__":
    main()
