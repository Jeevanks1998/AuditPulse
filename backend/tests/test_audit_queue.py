"""Audits run one at a time: a second audit waits for the first to finish."""

import asyncio
import os
import tempfile

from journey import run_lock


def test_second_audit_waits(monkeypatch):
    monkeypatch.setattr(run_lock, "AUDIT_LOCK_PATH", os.path.join(tempfile.mkdtemp(), "audit.lock"))
    order = []

    async def audit(name, hold):
        async with run_lock.audit_slot(max_wait_s=10, poll_s=0.05):
            order.append(f"start {name}")
            await asyncio.sleep(hold)
            order.append(f"end {name}")

    async def both():
        first = asyncio.create_task(audit("A", 0.3))
        await asyncio.sleep(0.05)
        await asyncio.gather(first, audit("B", 0))

    asyncio.run(both())
    assert order == ["start A", "end A", "start B", "end B"]


def test_waits_at_most_max_wait(monkeypatch):
    monkeypatch.setattr(run_lock, "AUDIT_LOCK_PATH", os.path.join(tempfile.mkdtemp(), "audit.lock"))

    async def run():
        async with run_lock.audit_slot(max_wait_s=10, poll_s=0.05):
            async with run_lock.audit_slot(max_wait_s=0.2, poll_s=0.05) as waited:
                return waited

    assert asyncio.run(run()) >= 0.2


def test_failure_reason_is_never_empty():
    import httpx
    from services.audit_service import failure_reason
    assert "reset the connection" in failure_reason(httpx.RemoteProtocolError(""))
    assert "did not respond" in failure_reason(httpx.ReadTimeout(""))
    assert failure_reason(RuntimeError("Failed to fetch x: HTTP 503")) == "Failed to fetch x: HTTP 503"
    assert failure_reason(ValueError()) == "ValueError"
