"""Security regressions: SSRF guard, settings mass-assignment, email caps, role gates."""

import asyncio

import pytest

from config.settings import settings


@pytest.fixture
def guard_on():
    settings.ALLOW_PRIVATE_NETWORK_TARGETS = False
    from utils import net_guard
    net_guard._dns_cache.clear()
    yield net_guard
    settings.ALLOW_PRIVATE_NETWORK_TARGETS = True


@pytest.mark.parametrize("url", [
    "http://localhost:8000/", "http://127.0.0.1/", "http://[::1]/", "http://10.0.0.5/admin",
    "http://192.168.1.1/", "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data/",
    "http://100.64.0.1/", "http://0.0.0.0/", "http://redis.railway.internal:6379/", "http://intranet/",
    "http://printer.local/", "file:///etc/passwd", "ftp://example.com/", "http://user:pw@example.com/",
    "http://[::ffff:127.0.0.1]/",
])
def test_private_and_internal_targets_are_blocked(guard_on, url):
    assert not guard_on.is_url_allowed(url)


def test_public_ip_is_allowed(guard_on):
    assert guard_on.is_url_allowed("http://8.8.8.8/")


def test_audit_create_rejects_internal_url(guard_on):
    from pydantic import ValidationError
    from schemas.audit import AuditCreate
    with pytest.raises(ValidationError) as e:
        AuditCreate(url="http://169.254.169.254/", modules=["consent"])
    assert "private or internal network" in str(e.value)


def test_schedule_create_rejects_internal_url(guard_on):
    from pydantic import ValidationError
    from api.scheduler import ScheduleCreate
    with pytest.raises(ValidationError):
        ScheduleCreate(url="localhost:6379")


def test_httpx_transport_blocks_redirect_hop(guard_on):
    import httpx

    async def run():
        async with guard_on.guarded_async_client() as client:
            await client.get("http://127.0.0.1:9/")
    with pytest.raises(httpx.ConnectError):
        asyncio.run(run())


def test_settings_update_cannot_change_email_or_role():
    from api.settings import SettingsUpdate
    u = SettingsUpdate(name="X", email="other@example.com", role="Admin", auditpulse_access=True)
    assert u.model_dump(exclude_unset=True) == {"name": "X"}


def test_email_recipient_caps():
    from pydantic import ValidationError
    from schemas.email import EmailSendRequest
    with pytest.raises(ValidationError):
        EmailSendRequest(to=[f"u{i}@example.com" for i in range(21)])


def test_viewer_cannot_delete_or_restore_audits():
    import inspect
    from api import history
    for fn in (history.delete_history_item, history.restore_history_item):
        dep = inspect.signature(fn).parameters["current_user"].default.dependency
        assert dep.__name__ == "_dependency"   # require_module(...), not plain get_current_user


def test_weak_secret_refused_with_remote_database(monkeypatch):
    import main
    monkeypatch.setattr(settings, "SECRET_KEY", main._DEFAULT_SECRET)
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://u:p@db.supabase.co:6543/postgres")
    with pytest.raises(RuntimeError):
        main._check_secrets()
    monkeypatch.setattr(settings, "SECRET_KEY", "x" * 48)
    main._check_secrets()


def test_browser_cannot_open_internal_address(guard_on):
    """Chromium contexts opened through launch_chromium refuse private addresses."""
    import http.server
    import threading

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    async def run():
        from playwright.async_api import async_playwright
        from config.browser import launch_chromium
        async with async_playwright() as pw:
            browser = await launch_chromium(pw, args=["--no-proxy-server"])
            ctx = await browser.new_context()
            page = await ctx.new_page()
            try:
                await page.goto(f"http://127.0.0.1:{port}/", timeout=8000)
                return "loaded"
            except Exception as exc:  # noqa: BLE001
                return str(exc)
            finally:
                await browser.close()
    try:
        out = asyncio.run(run())
    finally:
        srv.shutdown()
    assert out != "loaded" and "ERR_BLOCKED_BY_CLIENT" in out, out
