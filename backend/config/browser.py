"""
config/browser.py

The one place every headless-Chromium launch in the app goes through
(crawler/screenshots.py, consent/*, analytics/runtime.py, and journey/ via
analytics.runtime.open_runtime_browser).

Why: Chromium's defaults assume a desktop machine. Inside a container
(Docker on Railway) two of them break real audits:

  * /dev/shm is tiny (64 MB by default), and Chromium keeps its shared
    memory there. Heavy pages (big Next.js sites, many iframes) exhaust it
    and the browser dies mid-scan with
    "Target page, context or browser has been closed".
  * Site isolation starts a separate renderer process for every
    cross-site iframe (ads, CMPs, embeds). On a 1 GB service those extra
    processes push the container over its memory limit and the kernel
    kills Chromium.

CHROMIUM_ARGS turns both off and trims other background work. Nothing here
changes what a page does or which requests it makes, so tracking/consent
evidence is unaffected.
"""

from __future__ import annotations

import os
from typing import List

CHROMIUM_ARGS: List[str] = [
    "--disable-dev-shm-usage",          # use /tmp instead of the tiny /dev/shm
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",  # no Chrome-internal update/telemetry requests
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-sync",
    "--no-first-run",
    "--mute-audio",
    # One renderer per tab rather than one per cross-site frame: the
    # single biggest memory saving on ad/CMP-heavy pages.
    "--disable-features=site-per-process,IsolateOrigins,Translate,MediaRouter,BackForwardCache",
    "--disable-site-isolation-trials",
    "--renderer-process-limit=2",
    # Cap each page's JS heap: a runaway page fails on its own instead of
    # dragging the whole container over its memory limit.
    "--js-flags=--max-old-space-size=512",
    "--disable-backgrounding-occluded-windows",
    "--autoplay-policy=user-gesture-required",   # no auto-playing hero videos
    # Don't announce "controlled by automation" (navigator.webdriver): the
    # audit should see the same page a visitor's Chrome gets.
    "--disable-blink-features=AutomationControlled",
]

# Optional extra flags without a code change, e.g. CHROMIUM_EXTRA_ARGS="--no-sandbox".
_EXTRA = [a for a in os.getenv("CHROMIUM_EXTRA_ARGS", "").split() if a]


def chromium_args() -> List[str]:
    return CHROMIUM_ARGS + _EXTRA


def _use_regular_chrome_identity(browser) -> None:
    """Headless Chromium's user agent says "HeadlessChrome", which many sites
    and bot filters treat differently from a visitor's browser. Use the
    regular Chrome user agent of the same version (plus an AuditPulse token
    the site owner can allowlist) unless a caller sets its own."""
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
    """`await launch_chromium(pw)` instead of `await pw.chromium.launch()`."""
    args = list(kwargs.pop("args", []) or []) + chromium_args()
    browser = await pw.chromium.launch(args=args, **kwargs)
    _use_regular_chrome_identity(browser)
    # Every context this browser opens refuses private / internal network
    # addresses (SSRF protection — see utils/net_guard.py).
    from utils.net_guard import install_browser_guard
    return install_browser_guard(browser)


async def goto_page(page, url: str, timeout: int = 25_000, load_wait_ms: int = 8_000):
    """Navigate without failing on one slow third-party asset.

    `wait_until="load"` waits for every image, video and ad on the page; on
    heavy sites (or from a far-away region) that regularly exceeds the
    timeout even though the page is fully usable. Wait for
    DOMContentLoaded, then give "load" a capped extra wait.
    """
    resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    try:
        await page.wait_for_load_state("load", timeout=load_wait_ms)
    except Exception:  # noqa: BLE001 — still loading a slow asset; the page is usable
        pass
    return resp
