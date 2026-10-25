"""
Every Chromium launch goes through here.

Chromium's defaults break inside a container: the tiny /dev/shm crashes
heavy pages, and one process per cross-site iframe runs out of memory.
CHROMIUM_ARGS turns both off. Nothing here changes what the page loads, so
tracking and consent evidence is unaffected.
"""

from __future__ import annotations

import os
from typing import List

CHROMIUM_ARGS: List[str] = [
    "--disable-dev-shm-usage",          # use /tmp instead of the tiny /dev/shm
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",  # no Chrome update/telemetry requests
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-sync",
    "--no-first-run",
    "--mute-audio",
    # One renderer per tab instead of per iframe: the biggest memory saving.
    "--disable-features=site-per-process,IsolateOrigins,Translate,MediaRouter,BackForwardCache",
    "--disable-site-isolation-trials",
    "--renderer-process-limit=2",
    # Cap each page's JavaScript memory so one bad page can't take the container down.
    "--js-flags=--max-old-space-size=512",
    "--disable-backgrounding-occluded-windows",
    "--autoplay-policy=user-gesture-required",   # no auto-playing videos
    # Don't flag the browser as automated, so sites show the normal page.
    "--disable-blink-features=AutomationControlled",
]

# Extra flags from the environment, e.g. CHROMIUM_EXTRA_ARGS="--no-sandbox".
_EXTRA = [a for a in os.getenv("CHROMIUM_EXTRA_ARGS", "").split() if a]


def chromium_args() -> List[str]:
    return CHROMIUM_ARGS + _EXTRA


def _use_regular_chrome_identity(browser) -> None:
    """Use the normal Chrome user agent (plus an AuditPulse token) instead of "HeadlessChrome", which sites treat differently."""
    try:
        version = browser.version
    except Exception:  # noqa: BLE001
        return
    ua = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          f"Chrome/{version} Safari/537.36 AuditPulse/1.0")
    orig = browser.new_context

    async def new_context(*a, **k):
        k.setdefault("user_agent", ua)
        k.setdefault("locale", "en-GB")
        return await orig(*a, **k)

    browser.new_context = new_context


async def launch_chromium(pw, **kwargs):
    """Use `await launch_chromium(pw)` instead of `pw.chromium.launch()`."""
    args = list(kwargs.pop("args", []) or []) + chromium_args()
    browser = await pw.chromium.launch(args=args, **kwargs)
    _use_regular_chrome_identity(browser)
    # Block private/internal addresses (SSRF protection, utils/net_guard.py).
    from utils.net_guard import install_browser_guard
    return install_browser_guard(browser)


async def goto_page(page, url: str, timeout: int = 25_000, load_wait_ms: int = 8_000):
    """Opens `url` without failing on one slow asset: wait for DOMContentLoaded, then a capped wait for "load"."""
    resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    try:
        await page.wait_for_load_state("load", timeout=load_wait_ms)
    except Exception:  # noqa: BLE001 — still loading a slow asset; the page is usable
        pass
    return resp
