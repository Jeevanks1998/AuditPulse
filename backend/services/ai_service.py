"""
services/ai_service.py

Thin service-layer wrapper around the ai/ package (see ai/__init__.py for
what lives where) for the "ai" audit module (config.constants.AUDIT_MODULES
and the AI checkbox on audit.html) and for a future AI-assistant panel on
report.html. `generate_ai_findings` is called from services.audit_service's
pipeline whenever a run includes the "ai" module; the rest are the
service-layer entry points a router (api/ai.py) calls into.

Every findings-shaped dict returned here matches the same
{module, severity, title, description} shape as the other placeholder
modules in audit_service, so it flows through sync_issues_from_findings
and report_service without any special-casing.

Nothing in this module makes an HTTP call itself anymore — that all moved
to ai/provider.py — this file just resolves a completed Audit into the
plain arguments (url, breakdown, findings) each ai.* function needs, and
keeps the async-facing shape services.report_service / a future api/ai.py
router expects.
"""

from typing import Dict, List, Optional

from ai import (
    ActionPlan,
    ask_about_audit,
    generate_action_plan,
    generate_business_impact,
    generate_executive_summary,
    generate_recommendations,
    top_priorities,
)
from ai.priority import PrioritizedFinding
from fastapi import HTTPException, status
from models.audit import Audit
from models.user import User
from sqlalchemy.ext.asyncio import AsyncSession


async def generate_ai_findings(url: str, breakdown: dict) -> List[dict]:
    """Called by services.audit_service's pipeline for the "ai" module's findings."""
    return await generate_recommendations(url, breakdown)


# --------------------------------------------------------------------------
# Owned-audit lookup, shared by every AI-panel endpoint below
# --------------------------------------------------------------------------
async def get_owned_completed_audit(audit_id: int, db: AsyncSession, user: User) -> Audit:
    audit = await db.get(Audit, audit_id)
    if not audit or audit.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")
    if audit.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This audit hasn't finished running yet.",
        )
    return audit


# --------------------------------------------------------------------------
# AI-assistant panel (report.html) — one entry point per ai/ module
# --------------------------------------------------------------------------
async def get_executive_summary(audit_id: int, db: AsyncSession, user: User) -> str:
    audit = await get_owned_completed_audit(audit_id, db, user)
    return await generate_executive_summary(
        audit.url, audit.overall_score or 0, audit.breakdown or {}, audit.findings or []
    )


async def get_priorities(audit_id: int, db: AsyncSession, user: User) -> List[PrioritizedFinding]:
    audit = await get_owned_completed_audit(audit_id, db, user)
    return top_priorities(audit.findings or [], audit.breakdown or {})


async def get_business_impact(audit_id: int, db: AsyncSession, user: User) -> List[dict]:
    audit = await get_owned_completed_audit(audit_id, db, user)
    return await generate_business_impact(audit.url, audit.breakdown or {}, audit.findings or [])


async def get_action_plan(audit_id: int, db: AsyncSession, user: User) -> ActionPlan:
    audit = await get_owned_completed_audit(audit_id, db, user)
    return await generate_action_plan(audit.url, audit.breakdown or {}, audit.findings or [])


async def chat_about_audit(
    audit_id: int,
    question: str,
    db: AsyncSession,
    user: User,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    audit = await get_owned_completed_audit(audit_id, db, user)
    return await ask_about_audit(
        question,
        audit.url,
        audit.overall_score or 0,
        audit.breakdown or {},
        audit.findings or [],
        history,
    )
