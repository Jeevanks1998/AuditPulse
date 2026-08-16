"""
pdf/summary.py

Renders the executive summary and top-priorities highlights — the
prose-first section a reader sees right after the cover page, mirroring
reports/html_report.py's `_render_summary`. The AI-generated summary text
(ai/executive_summary.py) and the deterministic ranking from
ai/priority.py (surfaced on the payload as `priorities`, already the
top-N via `top_priorities`) are both best-effort/optional on
ReportPayload, so every builder here returns an empty list when its
input is missing rather than rendering an empty heading.
"""

from __future__ import annotations

from typing import List

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from pdf.theme import BORDER, STYLES, SURFACE_SUNKEN, esc, severity_color
from reports.generator import ReportPayload


def build_summary_flowables(payload: ReportPayload) -> List[Flowable]:
    flowables: List[Flowable] = []
    flowables.extend(_render_executive_summary(payload))
    flowables.extend(_render_top_priorities(payload))
    return flowables


def _render_executive_summary(payload: ReportPayload) -> List[Flowable]:
    if not payload.executive_summary:
        return []
    return [
        Paragraph("Executive Summary", STYLES["H1"]),
        Paragraph(esc(payload.executive_summary), STYLES["Body"]),
        Spacer(1, 6),
    ]


def _render_top_priorities(payload: ReportPayload) -> List[Flowable]:
    if not payload.priorities:
        return []

    header = ["#", "", "Finding", "Module"]
    rows = [header]
    for item in payload.priorities:
        badge = Paragraph(esc(item.severity.upper()), STYLES["TableCell"])
        title_cell = [Paragraph(f"<b>{esc(item.title)}</b>", STYLES["TableCell"])]
        if item.description:
            title_cell.append(Paragraph(esc(item.description), STYLES["TableCellMuted"]))
        rows.append([
            Paragraph(str(item.rank), STYLES["TableCell"]),
            badge,
            title_cell,
            Paragraph(esc(item.module), STYLES["TableCellMuted"]),
        ])

    table = Table(rows, colWidths=[16 * mm, 20 * mm, 100 * mm, 28 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURFACE_SUNKEN]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index, item in enumerate(payload.priorities, start=1):
        style.append(("BACKGROUND", (1, row_index), (1, row_index), severity_color(item.severity)))
        style.append(("TEXTCOLOR", (1, row_index), (1, row_index), colors.white))
        style.append(("ALIGN", (1, row_index), (1, row_index), "CENTER"))
    table.setStyle(TableStyle(style))

    return [
        Paragraph("Top Priorities", STYLES["H2"]),
        table,
        Spacer(1, 10),
    ]
