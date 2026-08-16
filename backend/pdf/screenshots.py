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
from reportlab.platypus import Flowable, Image, Paragraph, Spacer

from pdf.theme import STYLES, esc

MAX_WIDTH_MM = 170
MAX_HEIGHT_MM = 200


def build_screenshot_flowables(screenshot_path: Optional[str], url: str) -> List[Flowable]:
    """Returns the "Page Preview" section, or [] if there's nothing to embed."""
    if not screenshot_path:
        return []

    path = Path(screenshot_path)
    if not path.is_file():
        return []

    try:
        image = _scaled_image(path)
    except Exception:  # noqa: BLE001 — a corrupt/unreadable image should never break the PDF
        return []

    return [
        Paragraph("Page Preview", STYLES["H1"]),
        image,
        Paragraph(esc(url), STYLES["Caption"]),
        Spacer(1, 10),
    ]


def _scaled_image(path: Path) -> Image:
    image = Image(str(path))
    max_width = MAX_WIDTH_MM * mm
    max_height = MAX_HEIGHT_MM * mm

    scale = min(max_width / image.imageWidth, max_height / image.imageHeight, 1.0)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    image.hAlign = "CENTER"
    return image
