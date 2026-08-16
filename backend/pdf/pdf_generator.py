"""
pdf/pdf_generator.py

The single entry point for this package: turns a
reports.generator.ReportPayload into a complete PDF, as raw bytes, by
assembling the flowables from every other module in this package in a
fixed order — cover -> executive summary/top priorities -> score charts
-> page preview -> business impact/action plan -> full findings
appendix. This is the piece services.report_service.export_report_pdf's
docstring calls out as still missing; report_service is expected to call
`generate_pdf_report` and cache the resulting bytes the same way it
already caches JSON/HTML (reports/report_storage.py).

Each section module already degrades gracefully on missing input (no
executive summary, no action plan, no screenshot, etc. all just render
nothing) — this module doesn't re-check any of that, it only supplies
the page chrome (margins, running header/footer, page numbers) that no
individual section owns.
"""

from __future__ import annotations

from io import BytesIO
from typing import List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from pdf.appendix import build_appendix_flowables
from pdf.charts import build_charts_flowables
from pdf.cover import build_cover_flowables
from pdf.evidence import build_evidence_flowables
from pdf.recommendations import build_recommendations_flowables
from pdf.screenshots import build_screenshot_flowables
from pdf.summary import build_summary_flowables
from pdf.theme import BORDER, PAGE_MARGIN_MM, PDF_LAYOUT_VERSION, STYLES, esc
from reports.generator import ReportPayload

_COVER_TEMPLATE = "cover"
_CONTENT_TEMPLATE = "content"


def generate_pdf_report(payload: ReportPayload, screenshot_path: Optional[str] = None) -> bytes:
    """Renders `payload` to a complete PDF and returns it as bytes.

    `screenshot_path` is optional and best-effort — see pdf/screenshots.py;
    pass whatever path the caller already has (or None) and this function
    handles the rest, it never raises over a missing/unreadable image.
    """
    buffer = BytesIO()
    doc = _build_doc_template(buffer, payload)

    # cover.py's flowables always end in a PageBreak (its contract, see its
    # docstring) — NextPageTemplate has to land *before* that break, since a
    # PageBreak starts its new page with whatever template is already
    # queued at the moment it's processed, not one set immediately after.
    cover_flowables = build_cover_flowables(payload)
    story = []
    story.extend(cover_flowables[:-1])
    story.append(NextPageTemplate(_CONTENT_TEMPLATE))
    story.append(cover_flowables[-1])

    sections = [
        ("Executive Summary", build_summary_flowables(payload)),
        ("Score Breakdown", build_charts_flowables(payload)),
        ("Page Preview", build_screenshot_flowables(screenshot_path, payload.url)),
        ("Business Impact & Action Plan", build_recommendations_flowables(payload)),
        ("Analytics & Consent Evidence", build_evidence_flowables(payload)),
        ("Appendix: All Findings", build_appendix_flowables(payload)),
    ]

    # A generated section index (§3.2) built from whichever of the above
    # sections actually rendered flowables for this payload — never a
    # static list, and never page numbers, since ReportLab paginates the
    # tables/screenshots below dynamically and a hard-coded number would
    # drift out of sync immediately (§3.2 / §9).
    present_titles = [title for title, flowables in sections if flowables]
    story.extend(_build_toc_flowables(present_titles))

    for _title, flowables in sections:
        story.extend(flowables)

    doc.build(story)
    return buffer.getvalue()


def _build_toc_flowables(section_titles: List[str]) -> List[Flowable]:
    """A simple generated Table of Contents page: one numbered row per
    section that actually appears later in `story`, no page numbers."""
    if not section_titles:
        return []

    rows = [
        [Paragraph(f"{index}.", STYLES["TOCNumber"]), Paragraph(esc(title), STYLES["TOCEntry"])]
        for index, title in enumerate(section_titles, start=1)
    ]
    table = Table(rows, colWidths=[10 * mm, 150 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDER),
    ]))

    return [
        Paragraph("Table of Contents", STYLES["H1"]),
        Spacer(1, 6),
        table,
        PageBreak(),
    ]


def _build_doc_template(buffer: BytesIO, payload: ReportPayload) -> BaseDocTemplate:
    margin = PAGE_MARGIN_MM * mm
    width, height = A4

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=f"Website Audit Report - {payload.url}",
        author="AuditPulse",
        subject=f"AuditPulse PDF layout v{PDF_LAYOUT_VERSION}",
    )

    full_frame = Frame(margin, margin, width - 2 * margin, height - 2 * margin, id="full")
    content_frame = Frame(
        margin, margin, width - 2 * margin, height - 2 * margin - 10 * mm, id="content"
    )

    doc.addPageTemplates(
        [
            PageTemplate(id=_COVER_TEMPLATE, frames=[full_frame], onPage=_draw_cover_chrome),
            PageTemplate(id=_CONTENT_TEMPLATE, frames=[content_frame], onPage=_draw_content_chrome),
        ]
    )
    doc._auditpulse_url = payload.url  # noqa: SLF001 — cheapest way to reach the header from onPage
    return doc


def _draw_cover_chrome(canvas: Canvas, doc: BaseDocTemplate) -> None:
    # The cover page is deliberately chrome-free (no header/footer/page
    # number) — pdf/cover.py's content already fills the page.
    pass


def _draw_content_chrome(canvas: Canvas, doc: BaseDocTemplate) -> None:
    width, height = A4
    margin = PAGE_MARGIN_MM * mm

    canvas.saveState()
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)

    header_y = height - margin + 4 * mm
    canvas.line(margin, header_y - 2, width - margin, header_y - 2)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(STYLES["H2"].textColor)
    canvas.drawString(margin, header_y, "AuditPulse")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(STYLES["BodyMuted"].textColor)
    canvas.drawRightString(width - margin, header_y, _truncate(getattr(doc, "_auditpulse_url", ""), 70))

    footer_y = margin - 6 * mm
    canvas.line(margin, footer_y + 8, width - margin, footer_y + 8)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(STYLES["FooterText"].textColor)
    canvas.drawString(margin, footer_y, "Generated by AuditPulse")
    canvas.drawRightString(width - margin, footer_y, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"
