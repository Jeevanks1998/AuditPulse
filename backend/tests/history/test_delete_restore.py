"""Deleting an audit hides it from History / Recent Audits; restoring brings it back."""

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

pytest.importorskip("aiosqlite")


async def _scenario():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import models  # noqa: F401 — registers every table
    from config.database import Base
    from models.audit import Audit
    from models.history import History
    from models.user import User
    from services import history_service
    from services.audit_service import compute_stats, get_recent_audits
    from sqlalchemy import select

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        user = User(email="t@example.com", api_key="test-key")
        db.add(user)
        await db.flush()
        a1 = Audit(user_id=user.id, url="https://www.axa.de", label="Full site", status="completed", overall_score=93,
                   modules=["journey"])
        a2 = Audit(user_id=user.id, url="https://www.axa.it", label="Full site", status="completed", overall_score=64,
                   modules=["journey"])
        db.add_all([a1, a2])
        await db.commit()

        await history_service.delete_history_item(a1.id, db, user)
        recent = [a.url for a in await get_recent_audits(db, user)]
        assert recent == ["https://www.axa.it"]
        page = await history_service.list_history(db, user)
        assert [i.url for i in page.items] == ["https://www.axa.it"]
        bin_ = await history_service.list_history(db, user, deleted=True)
        assert [i.url for i in bin_.items] == ["https://www.axa.de"]
        stats = await compute_stats(db, user)
        assert stats.overall == 64          # the deleted audit no longer counts

        restored = await history_service.restore_history_item(a1.id, db, user)
        assert restored.deleted_at is None
        assert len(await get_recent_audits(db, user)) == 2
        events = (await db.execute(select(History.event_type))).scalars().all()
        assert "audit_deleted" in events and "audit_restored" in events
    await engine.dispose()


def test_delete_and_restore():
    asyncio.run(_scenario())
