"""
Full-page screenshots for reports. Returns None if the browser isn't available.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from config.logging import logger
from config.settings import settings
from config.browser import launch_chromium

DEFAULT_VIEWPORT = {"width": 1366, "height": 900}
NAVIGATION_TIMEOUT_MS = 20_000
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _screenshot_dir() -> Path:
    return Path(getattr(settings, "SCREENSHOT_DIR", "screenshots"))


def _safe_filename(hint: str) -> str:
    """Turns a URL/label into a safe file name."""
    stem = _SAFE_NAME_RE.sub("_", hint).strip("_") or "page"
    return stem[:150]  # stay under path-length limits


async def capture_screenshot(
    url: str,
    filename_hint: str,
    full_page: bool = True,
    viewport: Optional[dict] = None,
) -> Optional[str]:
    """Screenshots `url` and returns the file path, or None on any failure."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("screenshots.py: playwright not installed — skipping screenshot capture")
        return None

    out_dir = _screenshot_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_safe_filename(filename_hint)}.png"

    try:
        async with async_playwright() as pw:
            browser = await launch_chromium(pw)
            try:
                page = await browser.new_page(viewport=viewport or DEFAULT_VIEWPORT)
                await page.goto(url, wait_until="networkidle", timeout=NAVIGATION_TIMEOUT_MS)
                await page.screenshot(path=str(out_path), full_page=full_page)
            finally:
                await browser.close()
        return str(out_path)
    except Exception as exc:  # noqa: BLE001 — a failed screenshot should never break the audit
        logger.warning(f"screenshots.py: failed to capture {url}: {exc}")
        return None


async def capture_screenshots(urls_and_hints: list[tuple[str, str]]) -> dict[str, Optional[str]]:
    """{url: path or None} for a few pages."""
    results: dict[str, Optional[str]] = {}
    for url, hint in urls_and_hints:
        results[url] = await capture_screenshot(url, hint)
    return results
