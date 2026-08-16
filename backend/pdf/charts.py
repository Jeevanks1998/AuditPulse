"""
pdf/charts.py

Phase 2 (Professional Content Structure): draws "Overall Score & Module
Performance" (target structure §2 item 4) and "Finding Severity
Distribution" (item 5) as two separate sections.

Score & Module Performance:
  - a horizontal bar chart is the one primary chart (§3.4: "Keep one
    primary horizontal score chart"). The spider/radar chart from the
    original technical export is kept as an opt-in helper
    (`include_radar=True`) but is no longer built into the default PDF —
    "the bar chart is easier to read for exact values" (docx §1) and a
    reader shouldn't have to reconcile two shapes of the same data.
  - underneath the chart, a real module-by-module table (module label,
    score, status) so the exact numbers the bars only gesture at are
    also available as text — every row comes straight from
    `payload.score_grid`, so a module that wasn't scanned never appears
    (§3.4: "Do not create placeholder scores for modules that were not
    scanned"), and status wording reuses `pdf.theme.score_band` /
    `SCORE_BAND_LABELS`, the same bands `cover.py`'s ring and the
    frontend's score chips already use (§3.4: "same score-band logic as
    the application").

Finding Severity Distribution:
  - Critical / Warning / Info counts, shown as a small colored bar
    drawing plus a table with the exact numbers (§3.5). Both read
    `payload.severity_counts`, the one place reports/generator.py
    already computed this (§9/§11) — this module never recounts
    `payload.findings` itself, so it can't drift from the executive
    summary's metric card or the appendix's finding count.
"""

from __future__ import annotations

from typing import List

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.spider import SpiderChart
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from pdf.theme import (
    BORDER,
    ERROR,
    PRIMARY,
    PRIMARY_SOFT,
    SCORE_BAND_LABELS,
    STYLES,
    SUCCESS,
    SURFACE_SUNKEN,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
    esc,
    score_band,
    score_color,
)
from reports.generator import ReportPayload

CHART_WIDTH_MM = 170
RADAR_HEIGHT_MM = 78
BAR_HEIGHT_PER_ROW_MM = 9
BAR_HEIGHT_MIN_MM = 40

_SEVERITY_ORDER = ("critical", "warning", "info")
_SEVERITY_LABELS = {"critical": "Critical", "warning": "Warning", "info": "Info"}
_SEVERITY_CHART_COLORS = {"critical": ERROR, "warning": WARNING, "info": PRIMARY}
_BAND_COLORS = {"good": SUCCESS, "mid": WARNING, "bad": ERROR}


# --------------------------------------------------------------------------
# Overall Score & Module Performance (§3.4)
# --------------------------------------------------------------------------

def build_charts_flowables(payload: ReportPayload, include_radar: bool = False) -> List[Flowable]:
    """Returns the "Overall Score & Module Performance" section.

    `include_radar` defaults to False (§3.4: "Remove or make the radar
    chart optional; do not show both by default") — the bar chart plus
    the module table below it already cover both the shape and the exact
    values, so a caller has to opt in explicitly to also render the
    radar.
    """
    if not payload.score_grid:
        return []

    flowables: List[Flowable] = [Paragraph("Overall Score & Module Performance", STYLES["H1"])]
    if include_radar:
        flowables.append(_radar_drawing(payload))
        flowables.append(Spacer(1, 10))
    flowables.append(_bar_drawing(payload))
    flowables.append(Spacer(1, 10))
    flowables.append(_module_status_table(payload))
    flowables.append(Spacer(1, 10))
    return flowables


def _radar_drawing(payload: ReportPayload) -> Drawing:
    labels = [cell.label for cell in payload.score_grid]
    values = [cell.score for cell in payload.score_grid]

    width = CHART_WIDTH_MM * mm
    height = RADAR_HEIGHT_MM * mm
    drawing = Drawing(width, height)
    drawing.hAlign = "CENTER"

    chart = SpiderChart()
    chart.x = width * 0.22
    chart.y = 6
    chart.width = width * 0.56
    chart.height = height - 12
    chart.data = [values]
    chart.labels = labels
    chart.startAngle = 90
    chart.direction = "clockwise"
    chart.strands.strokeColor = PRIMARY
    chart.strands.strokeWidth = 1.75
    chart.strands.fillColor = PRIMARY_SOFT
    chart.strands[0].symbol = "Circle"
    chart.spokes.strokeColor = BORDER
    chart.spokeLabels.fontName = "Helvetica"
    chart.spokeLabels.fontSize = 7.5
    chart.spokeLabels.fillColor = TEXT_SECONDARY
    drawing.add(chart)
    return drawing


def _bar_drawing(payload: ReportPayload) -> Drawing:
    labels = [cell.label for cell in payload.score_grid]
    values = [cell.score for cell in payload.score_grid]

    width = CHART_WIDTH_MM * mm
    height = max(BAR_HEIGHT_MIN_MM, len(labels) * BAR_HEIGHT_PER_ROW_MM) * mm
    drawing = Drawing(width, height)
    drawing.hAlign = "CENTER"

    chart = HorizontalBarChart()
    chart.x = 34 * mm
    chart.y = 6
    chart.width = width - 34 * mm - 14
    chart.height = height - 12
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 7.5
    chart.categoryAxis.labels.fillColor = TEXT_PRIMARY
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = 100
    chart.valueAxis.valueStep = 25
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 7
    chart.bars.strokeWidth = 0
    for index, value in enumerate(values):
        chart.bars[(0, index)].fillColor = score_color(value)
    drawing.add(chart)
    return drawing


def _module_status_table(payload: ReportPayload) -> Table:
    """Module / Score / Status — the exact figures behind the bar chart above,
    banded with the same good/mid/bad logic as the rest of the app (§3.4)."""
    header = ["Module", "Score", "Status"]
    rows: List[list] = [header]
    status_rows: List[tuple] = []

    for row_index, cell in enumerate(payload.score_grid, start=1):
        band = score_band(cell.score)
        label = SCORE_BAND_LABELS.get(band, band.title())
        rows.append([
            Paragraph(esc(cell.label), STYLES["TableCell"]),
            Paragraph(f"{cell.score}/100", STYLES["TableCell"]),
            Paragraph(esc(label), STYLES["TableCell"]),
        ])
        status_rows.append((row_index, band))

    table = Table(rows, colWidths=[70 * mm, 30 * mm, 66 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURFACE_SUNKEN]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index, band in status_rows:
        style.append(("TEXTCOLOR", (2, row_index), (2, row_index), _BAND_COLORS.get(band, TEXT_PRIMARY)))
        style.append(("FONTNAME", (2, row_index), (2, row_index), "Helvetica-Bold"))
    table.setStyle(TableStyle(style))
    return table


# --------------------------------------------------------------------------
# Finding Severity Distribution (§3.5)
# --------------------------------------------------------------------------

def build_severity_distribution_flowables(payload: ReportPayload) -> List[Flowable]:
    """Returns the "Finding Severity Distribution" section, or [] if there are no
    findings at all. Counts always come from `payload.severity_counts` — never
    recomputed here — so this can't drift from the executive summary's metric
    card or the appendix's total (§9/§11)."""
    counts = payload.severity_counts or {}
    total = sum(counts.get(key, 0) for key in _SEVERITY_ORDER)
    if total == 0:
        return []

    return [
        Paragraph("Finding Severity Distribution", STYLES["H1"]),
        Paragraph(
            f"{total} total finding(s) across all scanned modules, by severity.",
            STYLES["BodyMuted"],
        ),
        Spacer(1, 6),
        _severity_bar_drawing(counts, total),
        Spacer(1, 8),
        _severity_count_table(counts, total),
        Spacer(1, 10),
    ]


def _severity_bar_drawing(counts: dict, total: int) -> Drawing:
    """A single stacked horizontal bar, proportioned by each severity's share of `total`
    — a quick visual read of the finding mix before the exact table below it."""
    width = CHART_WIDTH_MM * mm
    height = 16 * mm
    drawing = Drawing(width, height)
    drawing.hAlign = "CENTER"

    x = 0.0
    bar_height = 10 * mm
    y = (height - bar_height) / 2
    for severity in _SEVERITY_ORDER:
        count = counts.get(severity, 0)
        if not count:
            continue
        segment_width = width * (count / total)
        drawing.add(
            Rect(x, y, segment_width, bar_height, fillColor=_SEVERITY_CHART_COLORS[severity], strokeWidth=0)
        )
        x += segment_width
    return drawing


def _severity_count_table(counts: dict, total: int) -> Table:
    header = ["Severity", "Count", "Share"]
    rows: List[list] = [header]
    for severity in _SEVERITY_ORDER:
        count = counts.get(severity, 0)
        share = f"{(count / total * 100):.0f}%" if total else "0%"
        rows.append([
            Paragraph(esc(_SEVERITY_LABELS[severity]), STYLES["TableCell"]),
            Paragraph(str(count), STYLES["TableCell"]),
            Paragraph(share, STYLES["TableCell"]),
        ])

    table = Table(rows, colWidths=[60 * mm, 40 * mm, 40 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURFACE_SUNKEN]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index, severity in enumerate(_SEVERITY_ORDER, start=1):
        style.append(("TEXTCOLOR", (0, row_index), (0, row_index), _SEVERITY_CHART_COLORS[severity]))
        style.append(("FONTNAME", (0, row_index), (0, row_index), "Helvetica-Bold"))
    table.setStyle(TableStyle(style))
    return table
