"""
journey/journey_screenshots.py

Visual evidence for discovered journey interactions:

    before interaction   → viewport screenshot (element scrolled into view)
    highlighted          → same view with the discovered element outlined and
                           labelled ("detected: CTA") so the evidence clearly
                           corresponds to the element
    after interaction    → viewport (or the destination page / opened modal /
                           focused form)
    page                 → full-page screenshot of each scanned page

Files are written under the existing screenshot directory (the one main.py
already serves at /screenshots), reusing crawler/screenshots.py's
directory and safe-filename helpers rather than a separate system:

    <SCREENSHOT_DIR>/journey/<scan_id>/<page-slug>/interaction_001_before.png
                                                   interaction_001_highlighted.png
                                                   interaction_001_after.png
    <SCREENSHOT_DIR>/journey/<scan_id>/pages/<page-slug>.png
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from config.logging import logger
from crawler.screenshots import _safe_filename, _screenshot_dir

HIGHLIGHT_ID = "__auditpulse_journey_highlight"

_HIGHLIGHT_JS = r"""
([sel, label]) => {
  const el = document.querySelector(sel);
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const box = document.createElement('div');
  box.id = '%(id)s';
  box.style.cssText = [
    'position:fixed', 'z-index:2147483647', 'pointer-events:none',
    'left:' + (r.left - 6) + 'px', 'top:' + (r.top - 6) + 'px',
    'width:' + (r.width + 12) + 'px', 'height:' + (r.height + 12) + 'px',
    'border:3px solid #E11D48', 'border-radius:8px',
    'box-shadow:0 0 0 4000px rgba(15,23,42,0.28)'
  ].join(';');
  const tag = document.createElement('div');
  tag.textContent = label;
  tag.style.cssText = [
    'position:absolute', 'left:-3px', (r.top > 40 ? 'top:-30px' : 'bottom:-30px'),
    'background:#E11D48', 'color:#fff', 'font:600 12px/1.2 system-ui,sans-serif',
    'padding:5px 8px', 'border-radius:6px', 'white-space:nowrap'
  ].join(';');
  box.appendChild(tag);
  document.documentElement.appendChild(box);
  return true;
}
""" % {"id": HIGHLIGHT_ID}

_UNHIGHLIGHT_JS = "() => { const b = document.getElementById('%s'); if (b) b.remove(); }" % HIGHLIGHT_ID


def page_slug(url: str) -> str:
    p = urlparse(url)
    path = (p.path or "/").strip("/") or "home"
    if p.query:
        path += "_" + p.query
    return _safe_filename(path)[:60] or "home"


class EvidenceWriter:
    """Writes journey screenshots for one scan and returns /screenshots-relative paths."""

    def __init__(self, scan_id: str) -> None:
        self.root = Path(_screenshot_dir()) / "journey" / _safe_filename(scan_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self.base = Path(_screenshot_dir())

    def _path(self, page_url: str, name: str) -> Path:
        d = self.root / page_slug(page_url)
        d.mkdir(parents=True, exist_ok=True)
        return d / name

    def relative(self, path: Optional[Path]) -> Optional[str]:
        if path is None:
            return None
        try:
            return str(Path(path).relative_to(self.base)).replace("\\", "/")
        except ValueError:
            return str(path)

    async def page_snapshot(self, page, page_url: str) -> Optional[str]:
        out = self.root / "pages" / f"{page_slug(page_url)}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            await page.screenshot(path=str(out), full_page=True, timeout=15_000)
            return self.relative(out)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"journey screenshots: page snapshot failed for {page_url}: {exc}")
            return None

    async def viewport(self, page, page_url: str, index: int, kind: str) -> Optional[str]:
        out = self._path(page_url, f"interaction_{index:03d}_{kind}.png")
        try:
            await page.screenshot(path=str(out), timeout=10_000)
            return self.relative(out)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"journey screenshots: {kind} capture failed on {page_url}: {exc}")
            return None

    async def element(self, page, selector: str, page_url: str, index: int, kind: str) -> Optional[str]:
        """Clip to one element (e.g. the form) — falls back to the viewport."""
        out = self._path(page_url, f"interaction_{index:03d}_{kind}.png")
        try:
            loc = page.locator(selector).first
            if await loc.count() and await loc.is_visible():
                await loc.screenshot(path=str(out), timeout=10_000)
                return self.relative(out)
        except Exception:  # noqa: BLE001
            pass
        return await self.viewport(page, page_url, index, kind)

    async def highlighted(self, page, selector: str, label: str, page_url: str, index: int) -> Optional[str]:
        try:
            ok = await page.evaluate(_HIGHLIGHT_JS, [selector, label])
        except Exception:  # noqa: BLE001
            ok = False
        path = await self.viewport(page, page_url, index, "highlighted") if ok else None
        try:
            await page.evaluate(_UNHIGHLIGHT_JS)
        except Exception:  # noqa: BLE001
            pass
        return path
