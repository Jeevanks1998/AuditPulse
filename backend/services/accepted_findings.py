"""
Findings a site's team has reviewed and marked:

- "accepted": an intentional, approved choice (e.g. a vendor approved by the
  DPO, a cookie declared as technical). Shown apart, out of the score and out
  of the priorities.
- "to_verify": kept in the report as "To be verified" (counted like Good to
  know), e.g. Piano Analytics that may run in a consent-exempt mode.

Marks are kept per website (models/accepted_finding.py), so every later audit
of the same site applies them too. The measured scores stay in
audit.raw_breakdown / raw_overall_score; audit.breakdown / overall_score hold
the scores with the marks applied.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.logging import logger

ACCEPTED = "accepted"
TO_VERIFY = "to_verify"
STATUSES = (ACCEPTED, TO_VERIFY)

_SPACE_RE = re.compile(r"\s+")


def fingerprint(module: str, title: str) -> str:
    """Identifies "the same finding" across audits of one site: module + title."""
    return f"{(module or 'general').strip().lower()}|{_SPACE_RE.sub(' ', (title or '').strip().lower())}"[:400]


def _original_severity(f: dict) -> str:
    return f.get("original_severity") or f.get("severity") or "info"


def raw_findings(findings: Iterable[dict]) -> List[dict]:
    """The findings as measured: marks removed, original severities restored."""
    out = []
    for f in findings or []:
        g = dict(f)
        g["severity"] = _original_severity(f)
        g.pop("original_severity", None)
        g.pop("review", None)
        out.append(g)
    return out


def apply_marks(findings: Iterable[dict], marks: Dict[str, dict]) -> List[dict]:
    """Copies of `findings` with each mark applied (`review` set; "to_verify" shown as info)."""
    out = []
    for f in raw_findings(findings):
        mark = marks.get(fingerprint(f.get("module", ""), f.get("title", "")))
        if mark:
            f["review"] = dict(mark)
            if mark.get("status") == TO_VERIFY and f.get("severity") != "info":
                f["original_severity"] = f["severity"]
                f["severity"] = "info"
        out.append(f)
    return out


def is_accepted(f: dict) -> bool:
    return (f.get("review") or {}).get("status") == ACCEPTED


def active_findings(findings: Iterable[dict]) -> List[dict]:
    """Findings that still count: everything except those marked accepted."""
    return [f for f in (findings or []) if not is_accepted(f)]


def accepted_findings(findings: Iterable[dict]) -> List[dict]:
    return [f for f in (findings or []) if is_accepted(f)]


# Scores


def _module_findings(findings: List[dict], module: str) -> List[dict]:
    return [f for f in findings if f.get("module") == module]


def _penalty_score(module: str, findings: List[dict]) -> Optional[int]:
    if module == "consent":
        from consent.consent_score import score_consent
        return score_consent(findings).overall
    if module == "analytics":
        from analytics.analytics_score import score_analytics
        return score_analytics(findings).overall
    return None


def _journey_score(interactions: List[dict], accepted_indices: set) -> Optional[int]:
    """Journey health score with accepted tracking gaps left out of the coverage (same formula as journey_qa)."""
    from journey.journey_interactions import CONVERSION_CLASSES, FORM

    def g(i, *keys):
        for k in keys:
            if k in i:
                return i[k]
        return None

    unique = [i for i in interactions if g(i, "duplicate_of", "duplicateOf") is None]
    tested = [i for i in unique if g(i, "tested")]
    if not tested:
        return None
    successful = [i for i in tested if g(i, "status") == "success"]

    def is_conv(i):
        c = g(i, "classification")
        return c in CONVERSION_CLASSES or c == FORM

    def tracked(i):
        return ((g(i, "tracking") or {}).get("status")) in ("tracked", "duplicate")

    conv_tested = [i for i in successful if is_conv(i)
                   and not (g(i, "index") in accepted_indices and not tracked(i))]
    conv_tracked = [i for i in conv_tested if tracked(i)]
    success_rate = len(successful) / len(tested)
    coverage = (len(conv_tracked) / len(conv_tested)) if conv_tested else 1.0
    evidence = [i for i in tested if (g(i, "screenshots") or {}).get("highlighted")
                or (g(i, "screenshots") or {}).get("before")]
    evidence_rate = min(1.0, len(evidence) / len(tested))
    return round(100 * (0.35 * success_rate + 0.45 * coverage + 0.20 * evidence_rate))


def rescore(raw_breakdown: dict, raw: List[dict], marked: List[dict],
            journey_interactions: Optional[List[dict]] = None) -> dict:
    """Module scores with the marks applied: the measured score moved by the marks' effect only."""
    breakdown = dict(raw_breakdown or {})
    for module in ("consent", "analytics"):
        if module not in breakdown or breakdown[module] is None:
            continue
        before = _penalty_score(module, _module_findings(raw, module))
        after = _penalty_score(module, _module_findings(active_findings(marked), module))
        if before is None or after is None:
            continue
        breakdown[module] = max(0, min(100, breakdown[module] + (after - before)))
    if "journey" in breakdown and journey_interactions:
        accepted_idx = {((f.get("journey") or {}).get("interaction_index"))
                        for f in accepted_findings(marked) if f.get("module") == "journey"}
        accepted_idx.discard(None)
        if accepted_idx:
            before = _journey_score(journey_interactions, set())
            after = _journey_score(journey_interactions, accepted_idx)
            if before is not None and after is not None:
                breakdown["journey"] = max(0, min(100, breakdown["journey"] + (after - before)))
    return breakdown


# Storage


async def marks_for_website(db: AsyncSession, website_id: Optional[int]) -> Dict[str, dict]:
    if not website_id:
        return {}
    from models.accepted_finding import AcceptedFinding

    rows = (await db.execute(select(AcceptedFinding).where(AcceptedFinding.website_id == website_id))).scalars().all()
    return {r.fingerprint: {"status": r.status, "note": r.note or "", "by": r.created_by_name or "",
                            "at": r.created_at.isoformat() if r.created_at else None,
                            "module": r.module, "title": r.title} for r in rows}


def apply_to_results(findings: List[dict], breakdown: dict, marks: Dict[str, dict],
                     journey_interactions: Optional[List[dict]] = None) -> tuple:
    """For the audit pipeline: (marked findings, scores with marks, measured scores or None if nothing applied)."""
    if not marks:
        return findings, breakdown, None
    marked = apply_marks(findings, marks)
    if not any(f.get("review") for f in marked):
        return findings, breakdown, None
    new_breakdown = rescore(breakdown, raw_findings(findings), marked, journey_interactions)
    return marked, new_breakdown, dict(breakdown)


async def reapply_to_audit(db: AsyncSession, audit) -> None:
    """Re-applies the site's current marks to one finished audit (findings, scores, issues, cached exports)."""
    from models.issue import sync_issues_from_findings
    from models.journey import Journey
    from reports import report_storage
    from services.audit_service import _compute_overall_score

    marks = await marks_for_website(db, audit.website_id)
    raw = raw_findings(audit.findings or [])
    raw_breakdown = copy.deepcopy(audit.raw_breakdown if audit.raw_breakdown is not None else (audit.breakdown or {}))
    marked = apply_marks(raw, marks)
    journey_interactions = None
    journey_row = (await db.execute(select(Journey).where(Journey.audit_id == audit.id))).scalar_one_or_none()
    if journey_row is not None:
        journey_interactions = journey_row.interactions or None
    if any(f.get("review") for f in marked):
        audit.raw_breakdown = raw_breakdown
        if audit.raw_overall_score is None:
            audit.raw_overall_score = audit.overall_score
        audit.breakdown = rescore(raw_breakdown, raw, marked, journey_interactions)
        audit.overall_score = _compute_overall_score(audit.breakdown)
    else:
        if audit.raw_breakdown is not None:
            audit.breakdown = raw_breakdown
            audit.overall_score = (audit.raw_overall_score if audit.raw_overall_score is not None
                                   else _compute_overall_score(raw_breakdown))
        audit.raw_breakdown = None
        audit.raw_overall_score = None
    audit.findings = marked
    if journey_row is not None:
        journey_row.findings = apply_marks(journey_row.findings or [], marks)
        if (audit.breakdown or {}).get("journey") is not None:
            journey_row.journey_score = audit.breakdown["journey"]
    await sync_issues_from_findings(db, audit, active_findings(marked))
    try:
        report_storage.invalidate(audit.id)
    except Exception:  # noqa: BLE001 — a stale cache is rebuilt on the next export anyway
        logger.warning(f"accepted_findings: could not clear cached exports for audit {audit.id}")


async def set_mark(db: AsyncSession, audit, user, module: str, title: str, status: Optional[str],
                   note: str = "") -> None:
    """Adds, changes (status accepted / to_verify) or removes (status None) a mark for the audit's site."""
    from models.accepted_finding import AcceptedFinding
    from models.website import get_or_create_website

    if not audit.website_id:
        site = await get_or_create_website(db, audit.user_id, audit.url)
        audit.website_id = site.id
        await db.flush()
    fp = fingerprint(module, title)
    row = (await db.execute(select(AcceptedFinding).where(
        AcceptedFinding.website_id == audit.website_id, AcceptedFinding.fingerprint == fp))).scalar_one_or_none()
    if status is None:
        if row is not None:
            await db.delete(row)
    else:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if row is None:
            row = AcceptedFinding(website_id=audit.website_id, fingerprint=fp, module=(module or "general")[:40],
                                  title=(title or "")[:300])
            db.add(row)
        row.status = status
        row.note = (note or "").strip()[:2000] or None
        row.created_by = getattr(user, "id", None)
        row.created_by_name = (getattr(user, "name", None) or getattr(user, "email", None) or "")[:200] or None
        row.created_at = datetime.now(timezone.utc)
    await db.flush()
    await reapply_to_audit(db, audit)
