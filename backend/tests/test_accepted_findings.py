"""
Findings marked "accepted" (intentional, e.g. DPO-approved vendors) or "to verify"
(AXA Italy pilot feedback): left out of the score and priorities, remembered for
the site, applied again on later audits, and reversible.
"""

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.accepted_findings import (  # noqa: E402
    ACCEPTED, TO_VERIFY, active_findings, apply_marks, apply_to_results, fingerprint, raw_findings, rescore,
)

PRE_CONSENT = {"module": "consent", "category": "behavior", "severity": "critical",
               "title": "Tracking requests sent before consent", "description": "Piano and Medallia fired."}
NOT_HELD = {"module": "consent", "category": "runtime", "severity": "critical",
            "title": "Scripts are not held back until consent", "description": "x"}
GA4 = {"module": "analytics", "category": "cross_page_consistency", "severity": "warning",
       "title": "Inconsistent Google Analytics 4 configuration across pages", "description": "x"}


def _marks(*pairs):
    return {fingerprint(f["module"], f["title"]): {"status": st, "note": "Approved by DPO"} for f, st in pairs}


def test_fingerprint_ignores_case_and_spacing():
    assert fingerprint("Consent", "Tracking  requests sent before consent ") == \
        fingerprint("consent", "tracking requests sent before consent")


def test_accepted_findings_leave_the_active_list_and_raise_the_score():
    findings = [PRE_CONSENT, NOT_HELD, GA4]
    marked = apply_marks(findings, _marks((PRE_CONSENT, ACCEPTED), (NOT_HELD, ACCEPTED)))
    assert [f["title"] for f in active_findings(marked)] == [GA4["title"]]
    raw_breakdown = {"consent": 40, "analytics": 80}
    new = rescore(raw_breakdown, raw_findings(findings), marked)
    assert new["consent"] > 40 and new["analytics"] == 80


def test_to_verify_is_shown_as_info_and_can_be_undone():
    marked = apply_marks([PRE_CONSENT], _marks((PRE_CONSENT, TO_VERIFY)))
    assert marked[0]["severity"] == "info" and marked[0]["original_severity"] == "critical"
    assert active_findings(marked)          # still listed
    assert raw_findings(marked)[0]["severity"] == "critical"
    assert "review" not in apply_marks(marked, {})[0]


def test_pipeline_helper_keeps_measured_scores():
    findings, breakdown, raw = apply_to_results([PRE_CONSENT, GA4], {"consent": 50, "analytics": 70},
                                                _marks((PRE_CONSENT, ACCEPTED)))
    assert raw == {"consent": 50, "analytics": 70}
    assert breakdown["consent"] > 50
    same, b2, raw2 = apply_to_results([GA4], {"analytics": 70}, {})
    assert raw2 is None and b2 == {"analytics": 70}


def test_accepted_journey_tracking_gap_leaves_the_coverage():
    interactions = [
        {"index": 1, "tested": True, "status": "success", "classification": "cta", "tracking": {"status": "tracked"},
         "screenshots": {"before": "a.png"}},
        {"index": 2, "tested": True, "status": "success", "classification": "form", "tracking": {"status": "not_tracked"},
         "screenshots": {"before": "b.png"}},
    ]
    gap = {"module": "journey", "severity": "warning", "title": "No analytics detected for form interaction: Quote",
           "journey": {"interaction_index": 2}}
    marked = apply_marks([gap], _marks((gap, ACCEPTED)))
    new = rescore({"journey": 78}, raw_findings([gap]), marked, interactions)
    assert new["journey"] == 100      # 35 + 45 * (1/1) + 20, was 35 + 45 * (1/2) + 20 ≈ 78


pytest.importorskip("aiosqlite")


async def _scenario():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import models  # noqa: F401 — registers every table
    from config.database import Base
    from models.audit import Audit
    from models.user import User
    from models.website import get_or_create_website
    from services.accepted_findings import marks_for_website, set_mark

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        user = User(email="t@example.com", api_key="k", name="Jeevan")
        db.add(user)
        await db.flush()
        site = await get_or_create_website(db, user.id, "https://www.axa.it")
        audit = Audit(user_id=user.id, website_id=site.id, url="https://www.axa.it", status="completed",
                      modules=["consent", "analytics"], breakdown={"consent": 40, "analytics": 80},
                      overall_score=58, findings=[dict(PRE_CONSENT), dict(GA4)])
        db.add(audit)
        await db.commit()

        await set_mark(db, audit, user, "consent", PRE_CONSENT["title"], ACCEPTED, "Approved by our DPO")
        await db.commit()
        assert audit.raw_breakdown == {"consent": 40, "analytics": 80} and audit.raw_overall_score == 58
        assert audit.breakdown["consent"] > 40 and audit.overall_score > 58
        assert audit.findings[0]["review"]["status"] == ACCEPTED and audit.findings[0]["review"]["by"] == "Jeevan"
        assert len(await marks_for_website(db, site.id)) == 1

        await set_mark(db, audit, user, "consent", PRE_CONSENT["title"], None)
        await db.commit()
        assert audit.breakdown == {"consent": 40, "analytics": 80} and audit.overall_score == 58
        assert audit.raw_breakdown is None and "review" not in audit.findings[0]
    await engine.dispose()


def test_mark_and_unmark_on_a_saved_audit():
    asyncio.run(_scenario())
