"""
pdf/pdf_generator.py

The single entry point for this package: turns a
reports.generator.ReportPayload into a complete PDF (bytes).

Layout (v6), written for someone who has never seen the tool:

  1. Cover            — site, date, overall score, module scores,
                        how many issues to fix now / soon, summary
  2. Start here       — the top 5 things to fix, what was checked,
                        how to read the labels
  3. Consent, Analytics, Customer Journey — the evidence per module
  4. Appendix         — full lists of affected places, pages, scan IDs

The raw findings are grouped by pdf.issues; nothing here re-derives
scores. Screenshots are re-encoded as small JPEGs (pdf.components
.load_image) so a report stays a few MB instead of 15+.
"""

from __future__ import annotations

from io import BytesIO
from typing import List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import BaseDocTemplate, CondPageBreak, Flowable, Frame, NextPageTemplate, PageBreak, PageTemplate

from pdf.appendix import build_appendix_flowables
from pdf.components import hostname
from pdf.cover import BAND_HEIGHT, build_cover_flowables, draw_cover_band, draw_cover_footer
from pdf.issues import group_findings
from pdf.modules import build_analytics_section, build_consent_section, build_journey_section
from pdf.overview import TOP_N, build_overview_flowables
from pdf.theme import BORDER, FONT_BODY, FONT_SEMIBOLD, PAGE_MARGIN_MM, PDF_LAYOUT_VERSION, TEXT_PRIMARY, TEXT_TERTIARY
from reports.generator import ReportPayload

_COVER = "cover"
_CONTENT = "content"
# Section order follows the module order on the web report.
_MODULE_SECTIONS = (("consent", build_consent_section),
                    ("analytics", build_analytics_section),
                    ("journey", build_journey_section))


def generate_pdf_report(payload: ReportPayload, screenshot_path: Optional[str] = None) -> bytes:
    """Renders `payload` to a complete PDF and returns it as bytes.

    `screenshot_path` is accepted for backwards compatibility and ignored:
    the redesigned report shows the consent/journey evidence screenshots
    instead of a separate homepage preview."""
    buffer = BytesIO()
    doc = _doc(buffer, payload)

    scores = {c.module: int(c.score) for c in payload.score_grid}
    issues = group_findings(payload.findings or [], scores)

    appendix = build_appendix_flowables(payload, issues[:TOP_N], shown_items=0)
    story: List[Flowable] = []
    cover = build_cover_flowables(payload, issues, has_appendix=bool(appendix))
    story += cover[:-1]
    story.append(NextPageTemplate(_CONTENT))
    story.append(cover[-1])

    story += build_overview_flowables(payload, issues)

    for _module, builder in _MODULE_SECTIONS:
        section = builder(payload)
        if section:
            story.append(PageBreak())
            story += section

    story += appendix
    doc.build(story)
    return buffer.getvalue()


def _doc(buffer: BytesIO, payload: ReportPayload) -> BaseDocTemplate:
    margin = PAGE_MARGIN_MM * mm
    width, height = A4
    doc = BaseDocTemplate(
        buffer, pagesize=A4,
        leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin,
        title=f"Website audit report — {hostname(payload.url)}",
        author="AuditPulse",
        subject=f"AuditPulse PDF layout v{PDF_LAYOUT_VERSION}",
    )
    cover_frame = Frame(margin, 16 * mm, width - 2 * margin, height - BAND_HEIGHT - 8 * mm - 16 * mm,
                        id="cover", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    content_frame = Frame(margin, margin, width - 2 * margin, height - 2 * margin - 8 * mm,
                          id="content", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    def on_cover(canvas: Canvas, _doc) -> None:
        draw_cover_band(canvas, payload)
        draw_cover_footer(canvas)

    def on_content(canvas: Canvas, _doc) -> None:
        _content_chrome(canvas, payload)

    doc.addPageTemplates([
        PageTemplate(id=_COVER, frames=[cover_frame], onPage=on_cover),
        PageTemplate(id=_CONTENT, frames=[content_frame], onPage=on_content),
    ])
    return doc


def _content_chrome(canvas: Canvas, payload: ReportPayload) -> None:
    width, height = A4
    margin = PAGE_MARGIN_MM * mm
    canvas.saveState()
    y = height - margin + 1 * mm
    canvas.setFont(FONT_SEMIBOLD, 8)
    canvas.setFillColor(TEXT_PRIMARY)
    canvas.drawString(margin, y, "AuditPulse")
    canvas.setFont(FONT_BODY, 8)
    canvas.setFillColor(TEXT_TERTIARY)
    canvas.drawString(margin + canvas.stringWidth("AuditPulse", FONT_SEMIBOLD, 8) + 2 * mm, y, "Website audit report")
    canvas.drawRightString(width - margin, y, hostname(payload.url))
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(margin, y - 2.5 * mm, width - margin, y - 2.5 * mm)

    fy = 9 * mm
    canvas.line(margin, fy + 4 * mm, width - margin, fy + 4 * mm)
    canvas.setFont(FONT_BODY, 7.5)
    canvas.drawString(margin, fy, "Generated by AuditPulse")
    canvas.setFont(FONT_SEMIBOLD, 7.5)
    canvas.drawCentredString(width / 2, fy, "Designed by Jeevan K S")
    canvas.setFont(FONT_BODY, 7.5)
    canvas.drawRightString(width - margin, fy, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()
