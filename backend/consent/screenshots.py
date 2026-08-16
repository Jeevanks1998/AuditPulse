"""
consent/screenshots.py

Captures a visual of the consent banner itself for the audit report —
distinct from crawler/screenshots.py's full-page capture, which is
taken after any banner has already been dismissed and isn't useful for
judging button parity/prominence at a glance. Reuses that module's
Playwright-availability and safe-filename handling rather than
duplicating them; this file only adds the banner-element-specific
capture logic on top.

Same degrade-gracefully contract as crawler/screenshots.py and
consent/network.py: every entry point returns None on any failure
(Playwright missing, banner not found, navigation timeout) rather than
raising, so a screenshot failure can never take down the rest of the
consent audit.
"""

from __future__ import annotations

from typing import Optional

from config.logging import logger
from crawler.screenshots import DEFAULT_VIEWPORT, NAVIGATION_TIMEOUT_MS, _safe_filename, _screenshot_dir

# CSS selectors tried in order to locate the banner element for a clipped
# screenshot. Deliberately broader than consent/banner.py's detection
# regexes (this only needs *a* match to clip to, false positives here just
# mean a slightly-off crop, not a wrong finding) — falls back to a full
# viewport capture when nothing matches.
_BANNER_SELECTORS = [
    "#onetrust-banner-sdk", "#onetrust-consent-sdk",
    "#CybotCookiebotDialog",
    ".cky-consent-container",
    "#osano-cm-window",
    ".truste_box_overlay, #trustarc-banner-overlay",
    "#qc-cmp2-container",
    "#iubenda-cs-banner",
    "#cmplz-cookiebanner-container",
    "#didomi-host",
    "[id*='cookie-banner'], [class*='cookie-banner']",
    "[id*='cookie-consent'], [class*='cookie-consent']",
    "[id*='consent-banner'], [class*='consent-banner']",
]


async def capture_banner_screenshot(url: str, filename_hint: str) -> Optional[str]:
    """
    Navigates to `url`, waits briefly for a banner to render, and
    screenshots just that element (clipped) if one of the known
    selectors matches — otherwise falls back to a full-viewport shot so
    the report still has something to show even for an unrecognized
    homegrown banner.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("consent/screenshots.py: playwright not installed — skipping banner screenshot")
        return None

    out_dir = _screenshot_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_safe_filename(filename_hint)}_banner.png"

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(viewport=DEFAULT_VIEWPORT)
                await page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
                await page.wait_for_timeout(1_500)  # let a client-side-rendered banner appear

                element = await _locate_banner(page)
                if element is not None:
                    await element.screenshot(path=str(out_path))
                else:
                    await page.screenshot(path=str(out_path))
            finally:
                await browser.close()
        return str(out_path)
    except Exception as exc:  # noqa: BLE001 — a failed screenshot should never break the audit
        logger.warning(f"consent/screenshots.py: failed to capture banner for {url}: {exc}")
        return None


async def _locate_banner(page):
    for selector in _BANNER_SELECTORS:
        locator = page.locator(selector).first
        try:
            if await locator.count() > 0 and await locator.is_visible():
                return locator
        except Exception:  # noqa: BLE001 — a bad selector match shouldn't abort the whole capture
            continue
    return None
