"""
pdf/charts.py

Draws the score breakdown as two complementary charts:

  - a spider/radar chart, the same shape as report.html's radar chart
    (assets/js/report.js -> Charts.renderRadar) — this is the module the
    html_report.py docstring means when it says a PDF renderer is "the
    natural next step" for that visual.
  - a horizontal bar chart alongside it, since a radar chart is good for
    seeing the overall shape but bad for reading an exact number off an
    axis; the bars give each module's score as a precise, sortable value.

Both are reportlab.graphics Drawings (vector, not embedded images), built
straight from `payload.score_grid` (reports/generator.py's `ScoreCell`
list) — no dependency on a browser or JS chart library.
"""

from __future__ import annotations

from typing import List

from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.spider import SpiderChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, Spacer

from pdf.theme import BORDER, PRIMARY, PRIMARY_SOFT, STYLES, TEXT_PRIMARY, TEXT_SECONDARY, score_color
from reports.generator import ReportPayload

CHART_WIDTH_MM = 170
RADAR_HEIGHT_MM = 78
BAR_HEIGHT_PER_ROW_MM = 9
BAR_HEIGHT_MIN_MM = 40


def build_charts_flowables(payload: ReportPayload) -> List[Flowable]:
    if not payload.score_grid:
        return []
    return [
        Paragraph("Score Breakdown", STYLES["H1"]),
        _radar_drawing(payload),
        Spacer(1, 10),
        _bar_drawing(payload),
        Spacer(1, 10),
    ]


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
