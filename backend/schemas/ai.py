"""
Request/response models for the AI endpoints (summary, priorities, impact, plan, chat).
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ExecutiveSummaryOut(BaseModel):
    audit_id: int
    summary: str


class PriorityItemOut(BaseModel):
    rank: int
    module: str
    severity: str
    title: str
    description: str
    recommendation: str = ""
    effort: str


class PrioritiesOut(BaseModel):
    audit_id: int
    priorities: List[PriorityItemOut]


class BusinessImpactItemOut(BaseModel):
    title: str
    affected_area: str
    impact: str
    severity: str


class BusinessImpactOut(BaseModel):
    audit_id: int
    items: List[BusinessImpactItemOut]


class ActionPlanStepOut(BaseModel):
    title: str
    module: str
    severity: str
    effort: str
    step: str


class ActionPlanOut(BaseModel):
    audit_id: int
    quick_wins: List[ActionPlanStepOut]
    short_term: List[ActionPlanStepOut]
    long_term: List[ActionPlanStepOut]


class ChatTurn(BaseModel):
    question: str
    answer: str


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    history: Optional[List[ChatTurn]] = None


class ChatResponse(BaseModel):
    audit_id: int
    answer: str
