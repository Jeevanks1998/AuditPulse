"""
utils/screenshots.py

Filesystem lifecycle helpers for captured screenshots, complementing
`crawler/screenshots.py` (which owns the actual Playwright capture —
see its docstring) and `consent/screenshots.py` (banner-specific
crops). This module doesn't capture anything; it manages the files
those two produce under `settings.SCREENSHOT_DIR`: encoding one for an
API response, checking disk usage, and pruning old captures.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Optional

from config.settings import settings
from utils.file_manager import FileManager
from utils.formatter import format_bytes
from utils.helpers import utc_now
from utils.logger import get_logger

logger = get_logger(__name__)


def _manager() -> FileManager:
    # Constructed per-call (cheap) rather than at import time, so a
    # SCREENSHOT_DIR change in settings (e.g. in tests) takes effect
    # without needing to re-import this module.
    return FileManager(getattr(settings, "SCREENSHOT_DIR", "screenshots"))


def screenshot_exists(path: str) -> bool:
    return Path(path).is_file()


def delete_screenshot(path: str) -> bool:
    """Removes one screenshot file. Returns False (rather than raising)
    if it's already gone — callers cleaning up after a deleted Audit
    shouldn't have to check existence first."""
    file_path = Path(path)
    if not file_path.is_file():
        return False
    try:
        file_path.unlink()
        return True
    except OSError as exc:
        logger.warning(f"screenshots: failed to delete {path}: {exc}")
        return False


def get_screenshot_size(path: str) -> int:
    """Size in bytes, or 0 if the file doesn't exist."""
    file_path = Path(path)
    return file_path.stat().st_size if file_path.is_file() else 0


def screenshot_to_data_uri(path: str) -> Optional[str]:
    """
    Base64-encodes a screenshot as a `data:image/png;base64,...` URI,
    for embedding directly in a JSON API response (api/audit.py,
    api/reports.py) without exposing a separate static-file route.
    Returns None if the file is missing — same degrade-gracefully
    contract as `crawler.screenshots.capture_screenshot`.
    """
    file_path = Path(path)
    if not file_path.is_file():
        return None

    mime_type, _ = mimetypes.guess_type(file_path.name)
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def screenshot_url_to_path(url: Optional[str]) -> Optional[str]:
    """
    Reverses main.py's `/screenshots` StaticFiles mount (which serves
    settings.SCREENSHOT_DIR by basename — see schemas.audit._screenshot_url)
    back into a real filesystem path. Used wherever a consumer only has the
    frontend-facing URL (e.g. ReportPayload.screenshots, built from
    ConsentOut's *_screenshot_url computed fields) but needs the actual file
    on disk — the PDF's evidence section and reports/evidence.py's ZIP
    export both go through here rather than duplicating the mount's naming
    convention.
    """
    if not url:
        return None
    filename = url.rsplit("/", 1)[-1]
    if not filename:
        return None
    path = Path(getattr(settings, "SCREENSHOT_DIR", "screenshots")) / filename
    return str(path) if path.is_file() else None


def cleanup_old_screenshots(max_age_days: int = 30) -> int:
    """
    Deletes screenshots older than `max_age_days` under
    settings.SCREENSHOT_DIR. Intended to run periodically (e.g. from
    scheduler/jobs.py) so a long-running instance doesn't accumulate
    unbounded disk usage from every historical audit's captures.
    Returns the number of files removed.
    """
    manager = _manager()
    cutoff = utc_now().timestamp() - (max_age_days * 86400)
    removed = 0

    for file_path in manager.list_files(pattern="**/*.png"):
        try:
            if file_path.stat().st_mtime < cutoff:
                file_path.unlink()
                removed += 1
        except OSError as exc:
            logger.warning(f"screenshots: cleanup failed for {file_path}: {exc}")

    if removed:
        logger.info(f"screenshots: cleanup removed {removed} file(s) older than {max_age_days}d")
    return removed


def total_screenshot_storage() -> str:
    """Human-readable total disk usage of settings.SCREENSHOT_DIR
    (e.g. for a settings/admin page), via `utils.formatter.format_bytes`."""
    manager = _manager()
    total = sum(f.stat().st_size for f in manager.list_files(pattern="**/*.png") if f.is_file())
    return format_bytes(total)


__all__ = [
    "screenshot_exists",
    "delete_screenshot",
    "get_screenshot_size",
    "screenshot_to_data_uri",
    "screenshot_url_to_path",
    "cleanup_old_screenshots",
    "total_screenshot_storage",
]
