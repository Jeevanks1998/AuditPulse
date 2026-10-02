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
    "--disable-features=site-per-process,IsolateOrigins,Translate,MediaRouter",
    "--disable-site-isolation-trials",
    "--renderer-process-limit=4",
]

# Optional extra flags without a code change, e.g. CHROMIUM_EXTRA_ARGS="--no-sandbox".
_EXTRA = [a for a in os.getenv("CHROMIUM_EXTRA_ARGS", "").split() if a]


def chromium_args() -> List[str]:
    return CHROMIUM_ARGS + _EXTRA


async def launch_chromium(pw, **kwargs):
    """`await launch_chromium(pw)` instead of `await pw.chromium.launch()`."""
    args = list(kwargs.pop("args", []) or []) + chromium_args()
    return await pw.chromium.launch(args=args, **kwargs)
