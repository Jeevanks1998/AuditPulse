"""
Opening a page for the consent checks without giving up on slow sites.

Large sites (e.g. axa.it) keep loading trackers and widgets long after the page
is usable, so Playwright's "load" event can take longer than the timeout. A
timed-out "load" used to fail the whole browser check, which then reported a
false "No cookie-consent banner detected".

open_page():
1. waits for "load" up to `timeout_ms`;
2. if that times out but the page did open (it has a URL and a DOM), it carries
   on with what has rendered;
3. if the page did not open at all, it tries once more, waiting only for the
   HTML ("domcontentloaded") with a longer timeout.
Only when both attempts fail is the error raised.
"""

from __future__ import annotations

from config.logging import logger

RETRY_TIMEOUT_MS = 45_000
DOM_WAIT_MS = 15_000


def _opened(page) -> bool:
    url = getattr(page, "url", "") or ""
    return bool(url) and url != "about:blank"


async def _settle_dom(page) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=DOM_WAIT_MS)
    except Exception:  # noqa: BLE001 — use whatever has rendered
        pass


async def open_page(page, url: str, timeout_ms: int) -> None:
    try:
        await page.goto(url, wait_until="load", timeout=timeout_ms)
        return
    except Exception as exc:  # noqa: BLE001
        if _opened(page):
            logger.info(f"consent: {url} still loading after {timeout_ms} ms; using the rendered page")
            await _settle_dom(page)
            return
        logger.info(f"consent: {url} did not open ({str(exc)[:120]}); retrying")
    await page.goto(url, wait_until="domcontentloaded", timeout=max(timeout_ms, RETRY_TIMEOUT_MS))


async def reload_page(page, timeout_ms: int) -> None:
    try:
        await page.reload(wait_until="load", timeout=timeout_ms)
    except Exception:  # noqa: BLE001
        if not _opened(page):
            raise
        await _settle_dom(page)
