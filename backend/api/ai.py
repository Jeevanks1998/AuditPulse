"""
api/ai.py

The AI-assistant panel behind a completed audit's report: executive
summary, prioritized findings, business impact, action plan, and a
free-text chat endpoint — one route per ai/ module, all requiring the
same "owned + completed" audit that api/reports.py checks for. Parses
requests and shapes responses only; every actual call into ai/ goes
through services.ai_service.
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import User, get_current_user
from config.database import get_db
from schemas.ai import (
    ActionPlanOut,
    BusinessImpactOut,
    ChatRequest,
    ChatResponse,
    ExecutiveSummaryOut,
    PrioritiesOut,
)
from services import ai_service

router = APIRouter()


@router.get("/{audit_id}/summary", response_model=ExecutiveSummaryOut)
async def executive_summary(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    summary = await ai_service.get_executive_summary(audit_id, db, current_user)
    return ExecutiveSummaryOut(audit_id=audit_id, summary=summary)


@router.get("/{audit_id}/priorities", response_model=PrioritiesOut)
async def priorities(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ranked = await ai_service.get_priorities(audit_id, db, current_user)
    return PrioritiesOut(audit_id=audit_id, priorities=ranked)


@router.get("/{audit_id}/business-impact", response_model=BusinessImpactOut)
async def business_impact(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = await ai_service.get_business_impact(audit_id, db, current_user)
    return BusinessImpactOut(audit_id=audit_id, items=items)


@router.get("/{audit_id}/action-plan", response_model=ActionPlanOut)
async def action_plan(
    audit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    plan = await ai_service.get_action_plan(audit_id, db, current_user)
    return ActionPlanOut(
        audit_id=audit_id,
        quick_wins=plan.quick_wins,
        short_term=plan.short_term,
        long_term=plan.long_term,
    )


@router.post("/{audit_id}/chat", response_model=ChatResponse)
async def chat(
    audit_id: int,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    history: List[dict] = [turn.model_dump() for turn in (payload.history or [])]
    answer = await ai_service.chat_about_audit(audit_id, payload.question, db, current_user, history)
    return ChatResponse(audit_id=audit_id, answer=answer)
