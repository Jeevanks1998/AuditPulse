"""
Caches report exports (JSON, HTML, PDF) on disk by audit id, so repeat
downloads don't rebuild them. PDF names include PDF_LAYOUT_VERSION, so a
layout change automatically skips old cached PDFs.
"""

from __future__ import annotations

from typing import Any, Optional

from config.settings import settings
from pdf.theme import PDF_LAYOUT_VERSION
from utils.file_manager import FileManager


def _manager() -> FileManager:
    # Created per call so a changed REPORTS_DIR (e.g. in tests) is picked up.
    return FileManager(settings.REPORTS_DIR)


def _pdf_filename(audit_id: int) -> str:
    return f"{audit_id}.v{PDF_LAYOUT_VERSION}.pdf"


def save_json(audit_id: int, data: Any) -> None:
    _manager().write_json(f"{audit_id}.json", data)


def load_json(audit_id: int) -> Optional[Any]:
    return _manager().read_json(f"{audit_id}.json")


def save_html(audit_id: int, html: str) -> None:
    _manager().write_text(f"{audit_id}.html", html)


def load_html(audit_id: int) -> Optional[str]:
    return _manager().read_text(f"{audit_id}.html")


def save_pdf(audit_id: int, pdf_bytes: bytes) -> None:
    _manager().write_bytes(_pdf_filename(audit_id), pdf_bytes)


def load_pdf(audit_id: int) -> Optional[bytes]:
    return _manager().read_bytes(_pdf_filename(audit_id))


def invalidate(audit_id: int) -> None:
    """Deletes this audit's cached exports (called when its results change)."""
    manager = _manager()
    for name in (f"{audit_id}.json", f"{audit_id}.html", _pdf_filename(audit_id)):
        try:
            manager.delete(name)
        except Exception:  # noqa: BLE001 — a missing/locked cache file must never fail an audit
            pass


__all__ = ["save_json", "load_json", "save_html", "load_html", "save_pdf", "load_pdf", "invalidate"]
