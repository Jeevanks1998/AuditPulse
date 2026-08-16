"""
pdf/screenshots.py

Embeds the captured page screenshot (crawler/screenshots.py) into the
PDF as a visual reference for the audited page. Screenshot capture is
already optional and best-effort upstream — Playwright is an optional
dependency (requirements.txt) and `capture_screenshot` returns None on
any failure rather than raising (see its docstring) — so this module
carries that same guarantee forward: a missing or unreadable image never
breaks PDF generation, it just means the section is omitted.

pdf_generator.py passes the path it gets from the caller (typically
whatever services.report_service resolved via crawler.screenshots for
the audit's homepage) straight through; this module has no opinion on
*how* that path was produced.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Image, Paragraph, Spacer, Table, TableStyle

from pdf.theme import BORDER, STYLES, SURFACE_SUNKEN, TEXT_TERTIARY, esc

MAX_WIDTH_MM = 170
MAX_HEIGHT_MM = 200

_FALLBACK_HEIGHT_MM = 50


def build_screenshot_flowables(screenshot_path: Optional[str], url: str) -> List[Flowable]:
    """Returns the "Page Preview" section. The heading always renders (§3.11's Page
    Evidence section is expected); when there's nothing to embed it shows a neutral
    "Evidence not captured" placeholder instead of silently disappearing (§10:
    "If a screenshot is unavailable, render a neutral evidence-not-captured state
    rather than a broken image.")."""
    image: Optional[Image] = None
    if screenshot_path:
        path = Path(screenshot_path)
        if path.is_file():
            try:
                image = _scaled_image(path)
            except Exception:  # noqa: BLE001 — a corrupt/unreadable image should never break the PDF
                image = None

    body: Flowable = image if image is not None else _evidence_not_captured()

    return [
        Paragraph("Page Preview", STYLES["H1"]),
        body,
        Paragraph(esc(url), STYLES["Caption"]),
        Spacer(1, 10),
    ]


def _evidence_not_captured() -> Table:
    """A neutral placeholder box standing in for a missing/broken screenshot."""
    cell = Paragraph("Evidence not captured", STYLES["BodyMuted"])
    box = Table([[cell]], colWidths=[MAX_WIDTH_MM * mm], rowHeights=[_FALLBACK_HEIGHT_MM * mm])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE_SUNKEN),
        ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_TERTIARY),
    ]))
    box.hAlign = "CENTER"
    return box


def _scaled_image(path: Path) -> Image:
    image = Image(str(path))
    max_width = MAX_WIDTH_MM * mm
    max_height = MAX_HEIGHT_MM * mm

    scale = min(max_width / image.imageWidth, max_height / image.imageHeight, 1.0)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    image.hAlign = "CENTER"
    return image
