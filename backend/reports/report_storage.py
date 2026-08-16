"""
reports/report_storage.py

Caches the outputs of reports/json_report.py, reports/html_report.py,
and pdf/pdf_generator.py on disk, keyed by audit id, under
settings.REPORTS_DIR — the same "filesystem, not a DB column" approach
crawler/screenshots.py uses for captured images (see its docstring).
Rebuilding a report means re-running the AI pipeline in
reports/generator.py, which costs a handful of provider calls (and, for
the PDF, re-rendering every chart/table on top of that); caching the
rendered output means a share link or repeat download doesn't pay that
cost every time.

This module only reads/writes files — it has no opinion on *when* to use
the cache vs. rebuild (that's services.report_service's call, since only
it knows whether the underlying audit could have changed).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from config.logging import logger
from config.settings import settings
from pdf.theme import PDF_LAYOUT_VERSION


def _reports_dir() -> Path:
    return Path(getattr(settings, "REPORTS_DIR", "reports_output"))


def _path_for(audit_id: int, extension: str) -> Path:
    return _reports_dir() / f"{audit_id}.{extension}"


def _pdf_path_for(audit_id: int) -> Path:
    """The PDF cache path is versioned on pdf.theme.PDF_LAYOUT_VERSION (§11 "Cache" /
    the PDF validation checklist's "not accidentally served from an outdated cache") —
    a layout change bumps the version, which changes the filename, so a stale PDF
    rendered under the old layout is never mistaken for a cache hit under the new one."""
    return _reports_dir() / f"{audit_id}.v{PDF_LAYOUT_VERSION}.pdf"


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------
def save_html(audit_id: int, html: str) -> str:
    """Writes the rendered HTML report to disk and returns the path it was written to."""
    out_dir = _reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = _path_for(audit_id, "html")
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


def load_html(audit_id: int) -> Optional[str]:
    """Returns the cached HTML report for `audit_id`, or None if nothing's cached yet."""
    path = _path_for(audit_id, "html")
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:  # noqa: BLE001 — a cache-read failure should never break the export
        logger.warning(f"report_storage: failed to read cached HTML for audit {audit_id}: {exc}")
        return None


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------
def save_json(audit_id: int, data: Any) -> str:
    """Writes the JSON report export to disk and returns the path it was written to."""
    out_dir = _reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = _path_for(audit_id, "json")
    out_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return str(out_path)


def load_json(audit_id: int) -> Optional[Any]:
    """Returns the cached JSON report for `audit_id`, or None if nothing's cached yet."""
    path = _path_for(audit_id, "json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"report_storage: failed to read cached JSON for audit {audit_id}: {exc}")
        return None


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def save_pdf(audit_id: int, pdf_bytes: bytes) -> str:
    """Writes the rendered PDF report to disk (under a layout-versioned filename,
    see `_pdf_path_for`) and returns the path it was written to."""
    out_dir = _reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = _pdf_path_for(audit_id)
    out_path.write_bytes(pdf_bytes)
    return str(out_path)


def load_pdf(audit_id: int) -> Optional[bytes]:
    """Returns the cached PDF report for `audit_id`, or None if nothing's cached for the
    *current* `PDF_LAYOUT_VERSION` — a PDF cached under a previous layout version is a
    miss here, not a hit, so callers naturally re-render instead of serving a stale layout."""
    path = _pdf_path_for(audit_id)
    if not path.exists():
        return None
    try:
        return path.read_bytes()
    except OSError as exc:  # noqa: BLE001 — a cache-read failure should never break the export
        logger.warning(f"report_storage: failed to read cached PDF for audit {audit_id}: {exc}")
        return None


# --------------------------------------------------------------------------
# Cleanup
# --------------------------------------------------------------------------
def delete_cached_report(audit_id: int) -> None:
    """Removes any cached HTML/JSON/PDF exports for `audit_id` (e.g. when an audit is deleted or
    re-run) — including PDFs cached under any previous `PDF_LAYOUT_VERSION`, so a re-run never
    leaves an orphaned old-layout PDF sitting next to the current one."""
    for extension in ("html", "json"):
        path = _path_for(audit_id, extension)
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:  # noqa: BLE001 — best-effort cleanup only
                logger.warning(f"report_storage: failed to delete {path}: {exc}")

    for pdf_path in _reports_dir().glob(f"{audit_id}.v*.pdf"):
        try:
            pdf_path.unlink()
        except OSError as exc:  # noqa: BLE001 — best-effort cleanup only
            logger.warning(f"report_storage: failed to delete {pdf_path}: {exc}")

    # Pre-versioning cache files (audit_id.pdf, from before PDF_LAYOUT_VERSION existed).
    legacy_pdf = _path_for(audit_id, "pdf")
    if legacy_pdf.exists():
        try:
            legacy_pdf.unlink()
        except OSError as exc:  # noqa: BLE001 — best-effort cleanup only
            logger.warning(f"report_storage: failed to delete {legacy_pdf}: {exc}")
