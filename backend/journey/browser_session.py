"""
journey/browser_session.py

A Chromium session for the Customer Journey scan that survives the
browser being killed part-way through.

Why: on a small container (Railway Trial ≈ 1 GB shared by uvicorn, the
Celery worker and Chromium) a long multi-page journey can push Chromium
past the memory limit. The kernel kills it and every later step fails with
"Target page, context or browser has been closed" — the scan reported
"25 pages, 0 tested". Instead of giving up, this session:

  * keeps the consent cookies (storage_state) so a relaunch is still in
    the "consent accepted" state,
  * relaunches Chromium + the context when it has died (max MAX_RESTARTS),
  * re-attaches the analytics TrackingCapture to every new context,
  * blocks audio/video downloads (resource type "media"), which are large
    and irrelevant to tracking/journey evidence.
"""

from __future__ import annotations

from typing import Any, Optional

from config.logging import logger

from config.browser import launch_chromium

MAX_RESTARTS = 6

_DEAD_MARKERS = (
    "has been closed",
    "target crashed",
    "browser closed",
    "connection closed",
    "page crashed",
    "browser has disconnected",
    "target closed",
)


def is_browser_dead_error(exc: BaseException | str | None) -> bool:
    msg = str(exc or "").lower()
    return any(m in msg for m in _DEAD_MARKERS)


async def _block_media(route) -> None:
    try:
        if route.request.resource_type == "media":
            await route.abort()
        else:
            await route.continue_()
    except Exception:  # noqa: BLE001 — page navigated away / context closing
        pass


class JourneyBrowser:
    def __init__(self, capture=None, viewport: Optional[dict] = None):
        self.capture = capture
        self.viewport = viewport
        self.browser = None
        self.context = None
        self.restarts = 0
        self._pw = None
        self._state: Optional[dict] = None

    # ------------------------------------------------------------ lifecycle
    async def __aenter__(self) -> "JourneyBrowser":
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        await self._launch()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self._close_current()
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:  # noqa: BLE001
                pass

    async def _launch(self) -> None:
        self.browser = await launch_chromium(self._pw)
        kwargs: dict[str, Any] = dict(accept_downloads=True, service_workers="block")
        if self.viewport:
            kwargs["viewport"] = self.viewport
        if self._state:
            kwargs["storage_state"] = self._state
        self.context = await self.browser.new_context(**kwargs)
        await self.context.route("**/*", _block_media)
        if self.capture is not None:
            await self.capture.attach(self.context)

    async def _close_current(self) -> None:
        for obj in (self.context, self.browser):
            if obj is None:
                continue
            try:
                await obj.close()
            except Exception:  # noqa: BLE001 — already dead
                pass
        self.context = None
        self.browser = None

    # -------------------------------------------------------------- helpers
    def alive(self) -> bool:
        try:
            return self.browser is not None and self.browser.is_connected()
        except Exception:  # noqa: BLE001
            return False

    async def save_state(self) -> None:
        """Remember cookies/localStorage (consent choice) for a relaunch."""
        if not self.alive():
            return
        try:
            self._state = await self.context.storage_state()
        except Exception:  # noqa: BLE001
            pass

    async def restart(self, reason: str = "") -> bool:
        """Fresh Chromium + context. Returns False once MAX_RESTARTS is used up."""
        if self.restarts >= MAX_RESTARTS:
            return False
        self.restarts += 1
        logger.warning(f"journey: restarting browser ({self.restarts}/{MAX_RESTARTS}) {reason[:160]}")
        await self.save_state()
        await self._close_current()
        await self._launch()
        return True

    async def new_page(self):
        if not self.alive() and not await self.restart("browser not connected"):
            raise RuntimeError("browser could not be restarted")
        try:
            return await self.context.new_page()
        except Exception as exc:  # noqa: BLE001
            if not await self.restart(str(exc)):
                raise
            return await self.context.new_page()
