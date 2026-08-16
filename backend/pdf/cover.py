"""
pdf/cover.py

Builds the title page flowables for the PDF export: the report title,
audited URL, a single "vitals ring" for the overall score (echoing the
ring-styled score chips described as the frontend's signature system in
assets/css/variables.css), and the generation metadata. This is always
the first thing pdf_generator.py adds to the document, followed
immediately by a PageBreak — no other module in this package needs to
know a cover page exists.
"""

from __future__ import annotations

from typing import List
from urllib.parse import urlparse

from reportlab.graphics.shapes import Circle, Drawing, String
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, PageBreak, Paragraph, Spacer

from pdf.theme import STYLES, TEXT_SECONDARY, TEXT_TERTIARY, esc, score_color
from reports.generator import ReportPayload

RING_DIAMETER_MM = 42


def _hostname(url: str) -> str:
    """The audited hostname (§3.1) — falls back to the raw URL if it doesn't parse as one."""
    parsed = urlparse(url if "://" in url else f"//{url}")
    return parsed.netloc or url


def _audit_date(generated_at: str) -> str:
    """Just the date portion of `generated_at` (an ISO timestamp) for the cover's "Audit Date" line;
    the full timestamp still appears lower on the cover, so nothing is lost, just de-duplicated."""
    return generated_at.split("T", 1)[0] if generated_at else ""


def _scope_line(payload: ReportPayload) -> str:
    """Comma-separated list of modules actually present in `score_grid` (§3.1) — never
    a hard-coded module list (§9), so the cover never claims to have scoped a module that wasn't run."""
    return ", ".join(cell.label for cell in payload.score_grid)


def _score_ring(score: int) -> Drawing:
    """A stroked ring plus a centered score number.

    reportlab's `Circle` has no partial-arc fill, so unlike the frontend's
    animated SVG progress ring, this draws a full colored ring rather than
    one proportional to the score — the number and color already carry
    that signal on a static, printed page.
    """
    size = RING_DIAMETER_MM * mm
    center = size / 2
    radius = size / 2 - 4
    color = score_color(score)

    drawing = Drawing(size, size)
    drawing.hAlign = "CENTER"
    drawing.add(Circle(center, center, radius, strokeColor=TEXT_TERTIARY, strokeWidth=1.5, fillColor=None))
    drawing.add(Circle(center, center, radius - 3, strokeColor=color, strokeWidth=5, fillColor=None))
    drawing.add(
        String(center, center - 6, str(score), fontName="Helvetica-Bold", fontSize=20,
               fillColor=color, textAnchor="middle")
    )
    drawing.add(
        String(center, center - 20, "/ 100", fontName="Helvetica", fontSize=8,
               fillColor=TEXT_SECONDARY, textAnchor="middle")
    )
    return drawing


def build_cover_flowables(payload: ReportPayload) -> List[Flowable]:
    """Returns the cover page's flowables, ending in a PageBreak.

    Deliberately clean (§3.1: "Keep the cover visually clean; do not put
    technical findings on the cover") — title, audited hostname, the score
    ring, audit date/ID, and a scope line naming the modules that actually
    ran. No findings, no tables, no technical evidence belongs here.
    """
    flowables: List[Flowable] = [
        Spacer(1, 60),
        Paragraph("Website Audit Report", STYLES["CoverTitle"]),
        Paragraph(esc(_hostname(payload.url)), STYLES["CoverSubtitle"]),
        Spacer(1, 24),
        _score_ring(payload.overall),
        Spacer(1, 24),
        Paragraph(f"Audit Date: {esc(_audit_date(payload.generated_at))}", STYLES["CoverMeta"]),
        Paragraph(f"Audit ID: {esc(payload.audit_id)}", STYLES["CoverMeta"]),
    ]
    scope_line = _scope_line(payload)
    if scope_line:
        flowables.append(Spacer(1, 10))
        flowables.append(Paragraph(f"Scope: {esc(scope_line)}", STYLES["CoverMeta"]))
    if payload.share_url:
        flowables.append(Spacer(1, 6))
        flowables.append(Paragraph(esc(payload.share_url), STYLES["CoverMeta"]))
    flowables.append(PageBreak())
    return flowables
