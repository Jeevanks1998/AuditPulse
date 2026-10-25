"""
Screenshot file helpers (existence, size, delete, data URIs, cleanup). Capturing happens elsewhere.
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
    # Created per call so a changed SCREENSHOT_DIR (e.g. in tests) is picked up.
    return FileManager(getattr(settings, "SCREENSHOT_DIR", "screenshots"))


def screenshot_exists(path: str) -> bool:
    return Path(path).is_file()


def delete_screenshot(path: str) -> bool:
    """Deletes one screenshot; False if it was already gone."""
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
    """Screenshot as a data:image/png;base64 URI; None if missing."""
    file_path = Path(path)
    if not file_path.is_file():
        return None

    mime_type, _ = mimetypes.guess_type(file_path.name)
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def screenshot_url_to_path(url: Optional[str]) -> Optional[str]:
    """"/screenshots/..." URL -> file path on disk (used by the PDF and evidence ZIP)."""
    if not url:
        return None
    filename = url.rsplit("/", 1)[-1]
    if not filename:
        return None
    path = Path(getattr(settings, "SCREENSHOT_DIR", "screenshots")) / filename
    return str(path) if path.is_file() else None


def cleanup_old_screenshots(max_age_days: int = 30) -> int:
    """Deletes screenshots older than `max_age_days`. Returns how many."""
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
    """Total screenshot disk usage, e.g. "12.3 MB"."""
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
