"""
Consent screenshots: banner, settings panel, after Reject, after Accept.
Cropped to the banner the browser check actually found (known selectors,
then the full view, as fallbacks). File names include scan_id so old images
are never reused. Returns None on failure.
"""

from __future__ import annotations

from typing import Optional, Tuple

from config.logging import logger
from consent.buttons import CONSENT_CONTAINER_SELECTORS
from crawler.screenshots import DEFAULT_VIEWPORT, NAVIGATION_TIMEOUT_MS, _safe_filename, _screenshot_dir
from config.browser import launch_chromium

# Fallback only; the detected banner is preferred.
_BANNER_SELECTORS = list(CONSENT_CONTAINER_SELECTORS)


def _out_path(url: str, hint: str, scan_id: Optional[str]):
    out_dir = _screenshot_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(url)[:110]
    suffix = f"_{_safe_filename(scan_id)}" if scan_id else ""
    return out_dir / f"{stem}_{hint}{suffix}.png"


async def capture_page_or_element(
    page,
    url: str,
    hint: str,
    scan_id: Optional[str] = None,
    element: Optional[Tuple[object, str]] = None,
) -> Optional[str]:
    """Screenshot, cropped (with padding) to the banner element when given, otherwise the view."""
    out_path = _out_path(url, hint, scan_id)
    try:
        if element is not None:
            frame, selector = element
            try:
                loc = frame.locator(selector).first
                if await loc.count() > 0 and await loc.is_visible():
                    if selector == "body" and frame is not page.main_frame:
                        # The banner is a whole CMP iframe: crop to the iframe.
                        iframe_el = await frame.frame_element()
                        box = await iframe_el.bounding_box()
                    else:
                        # bounding_box() is relative to the main page, also inside iframes.
                        box = await loc.bounding_box()
                    if box and box["width"] > 4 and box["height"] > 4:
                        vp = page.viewport_size or DEFAULT_VIEWPORT
                        pad = 12
                        x = max(0, box["x"] - pad)
                        y = max(0, box["y"] - pad)
                        clip = {
                            "x": x, "y": y,
                            "width": min(vp["width"] - x, box["width"] + 2 * pad),
                            "height": min(vp["height"] - y, box["height"] + 2 * pad),
                        }
                        if clip["width"] > 4 and clip["height"] > 4:
                            await page.screenshot(path=str(out_path), clip=clip)
                            return str(out_path)
            except Exception as exc:  # noqa: BLE001 — fall through to a viewport shot
                logger.info(f"consent/screenshots.py: element clip failed for {hint} on {url}: {exc}")
        await page.screenshot(path=str(out_path))
        return str(out_path)
    except Exception as exc:  # noqa: BLE001 — a failed screenshot should never break the scan
        logger.warning(f"consent/screenshots.py: failed to capture {hint} screenshot for {url}: {exc}")
        return None


async def capture_banner_screenshot(url: str, filename_hint: str, scan_id: Optional[str] = None) -> Optional[str]:
    """Banner screenshot when the browser check is off: same detection, then the same fallbacks."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("consent/screenshots.py: playwright not installed — skipping banner screenshot")
        return None

    from consent.runtime import CONTAINER_HANDLE, inventory_banner  # local import avoids a cycle

    try:
        async with async_playwright() as pw:
            browser = await launch_chromium(pw)
            try:
                context = await browser.new_context(viewport=DEFAULT_VIEWPORT, storage_state=None,
                                                    service_workers="block")
                page = await context.new_page()
                await page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
                await page.wait_for_timeout(1_500)  # let a JavaScript banner appear

                inv, handles = await inventory_banner(page)
                element = handles.get(CONTAINER_HANDLE) if inv.banner_detected else None
                if element is None:
                    fallback = await _locate_banner(page)
                    if fallback is not None:
                        element = (page.main_frame, fallback)
                return await capture_page_or_element(page, filename_hint, "banner", scan_id, element)
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 — a failed screenshot should never break the audit
        logger.warning(f"consent/screenshots.py: failed to capture banner for {url}: {exc}")
        return None


async def _locate_banner(page) -> Optional[str]:
    for selector in _BANNER_SELECTORS:
        locator = page.locator(selector).first
        try:
            if await locator.count() > 0 and await locator.is_visible():
                return selector
        except Exception:  # noqa: BLE001
            continue
    return None
