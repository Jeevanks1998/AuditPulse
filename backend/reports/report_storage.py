"""
reports/report_storage.py

On-disk cache for the three export formats services.report_service builds
(reports.json_report.to_json_report / reports.html_report.render_html_report
/ pdf.pdf_generator.generate_pdf_report), keyed by audit id under
settings.REPORTS_DIR — see utils/file_manager.py's FileManager for the
actual (path-traversal-safe) I/O. A repeat download hits this cache
instead of re-running the AI pipeline in reports.generator (or, for the
PDF, redrawing every chart); `force_refresh` in report_service bypasses it.

PDF filenames are versioned with pdf.theme.PDF_LAYOUT_VERSION
(`"<audit_id>.v<version>.pdf"`) so a PDF layout change invalidates every
previously-cached PDF automatically — load_pdf simply won't find a file at
the new version's path, no explicit cache-bust step needed. JSON/HTML
aren't layout-versioned the same way since their shape is the
ReportPayload data model itself (§8), not a rendered layout.
"""

from __future__ import annotations

from typing import Any, Optional

from config.settings import settings
from pdf.theme import PDF_LAYOUT_VERSION
from utils.file_manager import FileManager


def _manager() -> FileManager:
    # Constructed per-call (cheap), not at import time, so a REPORTS_DIR
    # change in settings (e.g. in tests) takes effect without a re-import —
    # same pattern as utils/screenshots.py's _manager().
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


__all__ = ["save_json", "load_json", "save_html", "load_html", "save_pdf", "load_pdf"]
