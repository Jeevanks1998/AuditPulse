"""
utils/screenshot_store.py

Keeps evidence screenshots available after the container's disk is wiped
(Railway redeploys/restarts) or when the audit ran on a different service
than the API (separate worker): see models/screenshot_blob.py.

  persist_new_screenshots(since)   after an audit — copy every screenshot
                                   written under SCREENSHOT_DIR since the
                                   audit started into the database
  load_screenshot(key)             for main.py's /screenshots route when the
                                   file isn't on disk
  restore_screenshots(urls)        before building a PDF / evidence ZIP /
                                   email attachment — write missing files
                                   back to disk so the existing file-based
                                   code keeps working
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from config.logging import logger
from config.settings import settings

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def _root() -> Path:
    return Path(getattr(settings, "SCREENSHOT_DIR", "screenshots"))


def _enabled() -> bool:
    return bool(getattr(settings, "SCREENSHOT_DB_ENABLED", True))


def safe_key(key: str) -> Optional[str]:
    """Normalise a "/screenshots/<key>" tail; None if it tries to escape the folder."""
    key = (key or "").replace("\\", "/").split("?", 1)[0].lstrip("/")
    if key.startswith("screenshots/"):
        key = key[len("screenshots/"):]
    parts = [p for p in key.split("/") if p]
    if not parts or any(p in ("..", ".") for p in parts):
        return None
    return "/".join(parts)


def key_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = str(url)
    if "/screenshots/" in url:
        url = url.split("/screenshots/", 1)[1]
    return safe_key(url)


def _compress(data: bytes) -> Tuple[bytes, str]:
    """Re-encode as a compact JPEG (keeps size in the database reasonable)."""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        im.load()
        if im.mode not in ("RGB", "L"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            try:
                bg.paste(im, mask=im.convert("RGBA").split()[-1])
            except Exception:  # noqa: BLE001
                bg.paste(im.convert("RGB"))
            im = bg
        max_w = int(getattr(settings, "SCREENSHOT_DB_MAX_WIDTH", 1280))
        max_h = int(getattr(settings, "SCREENSHOT_DB_MAX_HEIGHT", 8000))
        if im.width > max_w:
            im = im.resize((max_w, max(1, round(im.height * max_w / im.width))), Image.LANCZOS)
        if im.height > max_h:
            im = im.crop((0, 0, im.width, max_h))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=int(getattr(settings, "SCREENSHOT_DB_JPEG_QUALITY", 68)),
                optimize=True, progressive=True)
        return out.getvalue(), "image/jpeg"
    except Exception as exc:  # noqa: BLE001 — keep the original bytes rather than lose evidence
        logger.warning(f"screenshot_store: could not re-encode screenshot: {exc}")
        return data, "image/png"


def _files_since(since: datetime) -> List[Path]:
    root = _root()
    if not root.is_dir():
        return []
    cutoff = since.timestamp() - 5
    out = []
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in _IMAGE_EXT and p.stat().st_mtime >= cutoff:
                out.append(p)
        except OSError:
            continue
    return out


async def persist_new_screenshots(db, since: datetime) -> int:
    """Copy screenshots written since `since` into screenshot_blobs. Returns how many were stored."""
    if not _enabled():
        return 0
    from sqlalchemy import delete

    from models.screenshot_blob import ScreenshotBlob

    root = _root().resolve()
    files = _files_since(since)
    stored = 0
    for path in files:
        try:
            key = safe_key(str(path.resolve().relative_to(root)))
        except ValueError:
            continue
        if not key:
            continue
        try:
            content, ctype = _compress(path.read_bytes())
        except OSError:
            continue
        await db.execute(delete(ScreenshotBlob).where(ScreenshotBlob.key == key))
        db.add(ScreenshotBlob(key=key, content=content, content_type=ctype, size=len(content),
                              created_at=datetime.now(timezone.utc)))
        stored += 1
        if stored % 25 == 0:
            await db.flush()

    days = int(getattr(settings, "SCREENSHOT_DB_RETENTION_DAYS", 60) or 0)
    if days > 0:
        await db.execute(delete(ScreenshotBlob).where(
            ScreenshotBlob.created_at < datetime.now(timezone.utc) - timedelta(days=days)))
    await db.commit()
    if stored:
        logger.info(f"screenshot_store: stored {stored} screenshot(s) in the database")
    return stored


async def load_screenshot(key: str) -> Optional[Tuple[bytes, str]]:
    if not _enabled():
        return None
    key = safe_key(key)
    if not key:
        return None
    from config.database import AsyncSessionLocal
    from models.screenshot_blob import ScreenshotBlob

    async with AsyncSessionLocal() as db:
        row = await db.get(ScreenshotBlob, key)
        if row is None:
            # Consent screenshots are also looked up by bare file name.
            from sqlalchemy import select
            name = key.rsplit("/", 1)[-1]
            row = (await db.execute(select(ScreenshotBlob).where(ScreenshotBlob.key == name))).scalar_one_or_none()
        return (row.content, row.content_type) if row is not None else None


def collect_screenshot_urls(obj, out: Optional[Set[str]] = None) -> Set[str]:
    """Every "/screenshots/..." string anywhere inside a payload / dict / list."""
    out = set() if out is None else out
    if isinstance(obj, str):
        if "/screenshots/" in obj or obj.startswith("screenshots/"):
            out.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_screenshot_urls(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_screenshot_urls(v, out)
    elif hasattr(obj, "__dict__"):
        collect_screenshot_urls(vars(obj), out)
    return out


async def restore_screenshots(urls: Iterable[str]) -> int:
    """Write screenshots that are missing on disk back from the database."""
    if not _enabled():
        return 0
    keys = {k for k in (key_from_url(u) for u in urls) if k}
    root = _root()
    missing = [k for k in keys if not (root / k).is_file()]
    if not missing:
        return 0
    from sqlalchemy import select

    from config.database import AsyncSessionLocal
    from models.screenshot_blob import ScreenshotBlob

    restored = 0
    try:
        async with AsyncSessionLocal() as db:
            for i in range(0, len(missing), 100):
                chunk = missing[i:i + 100]
                rows = (await db.execute(select(ScreenshotBlob).where(ScreenshotBlob.key.in_(chunk)))).scalars().all()
                for row in rows:
                    dest = root / row.key
                    try:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(row.content)
                        restored += 1
                    except OSError as exc:
                        logger.warning(f"screenshot_store: could not restore {row.key}: {exc}")
    except Exception as exc:  # noqa: BLE001 — a report must never fail because of this
        logger.warning(f"screenshot_store: restore failed: {exc}")
    return restored


async def restore_for_payload(payload) -> int:
    return await restore_screenshots(collect_screenshot_urls(payload))


__all__ = ["persist_new_screenshots", "load_screenshot", "restore_screenshots", "restore_for_payload",
           "collect_screenshot_urls", "key_from_url", "safe_key"]
