"""
utils/file_manager.py

Generic, path-traversal-safe file I/O for anything new that needs to
read/write under one of the app's data directories (settings.REPORTS_DIR,
settings.SCREENSHOT_DIR, settings.LOG_FILE_PATH's parent, or an ad hoc
export directory). `reports/report_storage.py` and `crawler/screenshots.py`
already do their own narrow, purpose-built file I/O for their one job
each — this module doesn't replace either, it's what the *next* feature
that needs disk storage (an export format, an upload, a cache) should
build on instead of writing another one-off `Path(...).write_text(...)`.

Every method resolves paths against `base_dir` and refuses to write/read
outside of it, so a caller passing a filename built from user/external
input (an audit label, a URL-derived slug) can't be tricked into
escaping the intended directory via `../../` segments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


class PathTraversalError(ValueError):
    """Raised when a requested path would resolve outside `base_dir`."""


class FileManager:
    """A small sandboxed file store rooted at `base_dir`.

        reports = FileManager(settings.REPORTS_DIR)
        reports.write_json("42/summary.json", {"score": 87})
        data = reports.read_json("42/summary.json")
    """

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------
    def ensure_dir(self, sub_dir: str = "") -> Path:
        """Creates (if needed) and returns `base_dir / sub_dir`."""
        target = self._safe_path(sub_dir) if sub_dir else self.base_dir
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _safe_path(self, relative_path: str) -> Path:
        """Resolves `relative_path` under `base_dir`, raising
        `PathTraversalError` if the result would land outside it."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        candidate = (self.base_dir / relative_path).resolve()
        base_resolved = self.base_dir.resolve()
        if base_resolved != candidate and base_resolved not in candidate.parents:
            raise PathTraversalError(f"'{relative_path}' resolves outside of {self.base_dir}")
        return candidate

    # ------------------------------------------------------------------
    # Text / bytes
    # ------------------------------------------------------------------
    def write_text(self, relative_path: str, content: str, encoding: str = "utf-8") -> Path:
        path = self._safe_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        return path

    def read_text(self, relative_path: str, encoding: str = "utf-8") -> Optional[str]:
        path = self._safe_path(relative_path)
        if not path.is_file():
            return None
        return path.read_text(encoding=encoding)

    def write_bytes(self, relative_path: str, content: bytes) -> Path:
        path = self._safe_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def read_bytes(self, relative_path: str) -> Optional[bytes]:
        path = self._safe_path(relative_path)
        if not path.is_file():
            return None
        return path.read_bytes()

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------
    def write_json(self, relative_path: str, data: Any, indent: int = 2) -> Path:
        return self.write_text(relative_path, json.dumps(data, indent=indent, default=str))

    def read_json(self, relative_path: str) -> Optional[Any]:
        raw = self.read_text(relative_path)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"file_manager: {relative_path} is not valid JSON")
            return None

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------
    def exists(self, relative_path: str) -> bool:
        return self._safe_path(relative_path).exists()

    def delete(self, relative_path: str) -> bool:
        path = self._safe_path(relative_path)
        if path.is_file():
            path.unlink()
            return True
        return False

    def list_files(self, sub_dir: str = "", pattern: str = "*") -> List[Path]:
        target = self._safe_path(sub_dir) if sub_dir else self.base_dir
        if not target.is_dir():
            return []
        return sorted(p for p in target.glob(pattern) if p.is_file())

    def size_of(self, relative_path: str) -> int:
        path = self._safe_path(relative_path)
        return path.stat().st_size if path.is_file() else 0


__all__ = ["FileManager", "PathTraversalError"]
