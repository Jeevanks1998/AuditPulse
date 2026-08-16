"""
pdf/appendix.py

Renders every raw finding (`Audit.findings`, the same list
reports/html_report.py's `_render_findings` walks) as a single table —
the exhaustive, unprioritized backstop after the curated Top
Priorities (pdf/summary.py) and Action Plan (pdf/recommendations.py)
sections. Sorted by severity for scannability (critical first), using
the same rank ai/priority.py uses, but this is a display sort only —
unlike ai/priority.py's `prioritize_findings`, nothing here is re-used
by other modules, so it doesn't need to be the canonical ranking.
"""

from __future__ import annotations

from typing import List

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from pdf.theme import BORDER, STYLES, SURFACE_SUNKEN, esc, severity_color
from reports.generator import ReportPayload

_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def build_appendix_flowables(payload: ReportPayload) -> List[Flowable]:
    if not payload.findings:
        return []

    ordered = sorted(
        payload.findings,
        key=lambda f: (_SEVERITY_RANK.get(f.get("severity", "info"), 3),),
    )

    header = ["Severity", "Module", "Finding"]
    rows = [header]
    for finding in ordered:
        severity = finding.get("severity", "info")
        title_cell = [Paragraph(f"<b>{esc(finding.get('title', ''))}</b>", STYLES["TableCell"])]
        if finding.get("description"):
            title_cell.append(Paragraph(esc(finding["description"]), STYLES["TableCellMuted"]))
        rows.append([
            Paragraph(esc(severity.upper()), STYLES["TableCell"]),
            Paragraph(esc(finding.get("module", "")), STYLES["TableCellMuted"]),
            title_cell,
        ])

    table = Table(rows, colWidths=[24 * mm, 30 * mm, 110 * mm], repeatRows=1)
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
    for row_index, finding in enumerate(ordered, start=1):
        color = severity_color(finding.get("severity", "info"))
        style.append(("TEXTCOLOR", (0, row_index), (0, row_index), color))
        style.append(("FONTNAME", (0, row_index), (0, row_index), "Helvetica-Bold"))
    table.setStyle(TableStyle(style))

    return [
        Paragraph("Appendix: All Findings", STYLES["H1"]),
        Paragraph(f"{len(ordered)} finding(s) across all modules.", STYLES["BodyMuted"]),
        Spacer(1, 6),
        table,
    ]
