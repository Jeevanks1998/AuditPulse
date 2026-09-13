"""
pdf/appendix.py

Renders every raw finding (`Audit.findings`, the same list
reports/html_report.py's `_render_findings` walks) as a single table —
the exhaustive, unprioritized backstop after the curated Critical
Findings (pdf/summary.py) and Action Plan (pdf/recommendations.py)
sections. Sorted by severity for scannability (critical first), using
the same rank ai/priority.py uses, but this is a display sort only —
unlike ai/priority.py's `prioritize_findings`, nothing here is re-used
by other modules, so it doesn't need to be the canonical ranking.

Phase 2 (§3.6/§3.12/Table 9): every row now shows its Finding ID —
`reports/generator.py`'s `assign_finding_ids` already stamped one onto
every finding before it reached this payload, so this module only
displays it, never assigns one of its own. All findings are always kept
(§3.12: "Preserve all ... real findings" / §9: never drop real evidence);
only very long descriptions are trimmed for this table specifically
(§3.12: "Keep the main report concise; move very long URLs and raw
evidence to the appendix" — the appendix *is* that detail area, but a
multi-hundred-character description with an embedded URL still needs a
sane cap so one finding doesn't blow out a table row across several
pages).
"""

from __future__ import annotations

from typing import List

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from pdf.theme import BORDER, STYLES, SURFACE_SUNKEN, esc, severity_color
from reports.generator import ReportPayload

_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}

# A description beyond this is trimmed in the appendix table (with a
# trailing ellipsis) so one verbose finding — e.g. one embedding a long
# URL — can't blow out the row height across several pages; the full,
# untrimmed text is still available anywhere else the finding is used
# (the finding dict this module reads from is never mutated).
_MAX_DESCRIPTION_CHARS = 260


def build_appendix_flowables(payload: ReportPayload) -> List[Flowable]:
    if not payload.findings:
        return []

    ordered = sorted(
        payload.findings,
        key=lambda f: (
            _SEVERITY_RANK.get(f.get("severity", "info"), 3),
            f.get("module", ""),
            f.get("finding_id", ""),
        ),
    )

    header = ["Finding ID", "Severity", "Module", "Finding"]
    rows = [header]
    for finding in ordered:
        severity = finding.get("severity", "info")
        title_cell = [Paragraph(f"<b>{esc(finding.get('title', ''))}</b>", STYLES["TableCell"])]
        description = finding.get("description")
        if description:
            title_cell.append(Paragraph(esc(_truncate(description)), STYLES["TableCellMuted"]))
        rows.append([
            Paragraph(esc(finding.get("finding_id", "")), STYLES["TableCellMuted"]),
            Paragraph(esc(severity.upper()), STYLES["TableCell"]),
            Paragraph(esc(finding.get("module", "")), STYLES["TableCellMuted"]),
            title_cell,
        ])

    table = Table(rows, colWidths=[22 * mm, 20 * mm, 26 * mm, 96 * mm], repeatRows=1)
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
        style.append(("TEXTCOLOR", (1, row_index), (1, row_index), color))
        style.append(("FONTNAME", (1, row_index), (1, row_index), "Helvetica-Bold"))
    table.setStyle(TableStyle(style))

    return [
        Paragraph("Appendix: All Findings", STYLES["H1"]),
        Paragraph(f"{len(ordered)} finding(s) across all modules.", STYLES["BodyMuted"]),
        Spacer(1, 6),
        table,
    ]


def _truncate(text: str) -> str:
    if len(text) <= _MAX_DESCRIPTION_CHARS:
        return text
    return text[: _MAX_DESCRIPTION_CHARS - 1].rstrip() + "\u2026"
