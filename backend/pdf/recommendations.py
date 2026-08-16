"""
pdf/recommendations.py

Renders the two AI-generated "what to do about it" sections from
reports/generator.py's ReportPayload:

  - Business Impact (ai/business_impact.py) — why each problem matters,
    in plain-business terms, grouped by severity.
  - Action Plan (ai/action_plan.py) — the same findings regrouped into
    quick_wins / short_term / long_term horizons (ai/priority.py's
    deterministic effort estimate, not re-derived here).

Mirrors reports/html_report.py's `_render_business_impact` /
`_render_action_plan`, just as PDF flowables instead of HTML strings.
Both sections are additive/optional on the payload (`include_ai=False`
callers get neither), so each builder here returns [] when its input is
empty rather than printing an empty heading.
"""

from __future__ import annotations

from typing import Iterable, List

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from pdf.theme import BORDER, STYLES, SURFACE_SUNKEN, esc, severity_color
from reports.generator import ReportPayload

_HORIZONS = (
    ("Quick Wins", "quick_wins"),
    ("Short Term", "short_term"),
    ("Long Term", "long_term"),
)


def build_recommendations_flowables(payload: ReportPayload) -> List[Flowable]:
    flowables: List[Flowable] = []
    flowables.extend(_render_business_impact(payload))
    flowables.extend(_render_action_plan(payload))
    return flowables


def _render_business_impact(payload: ReportPayload) -> List[Flowable]:
    if not payload.business_impact:
        return []

    flowables: List[Flowable] = [Paragraph("Business Impact", STYLES["H1"])]
    for item in payload.business_impact:
        flowables.append(_impact_row(item))
    flowables.append(Spacer(1, 8))
    return flowables


def _impact_row(item: dict) -> Table:
    severity = item.get("severity", "info")
    badge = Paragraph(esc(severity.upper()), STYLES["Badge"])
    body = [
        Paragraph(
            f"<b>{esc(item.get('title', ''))}</b>"
            f"<font color='#64748B'>  &middot;  {esc(item.get('affected_area', ''))}</font>",
            STYLES["TableCell"],
        )
    ]
    if item.get("impact"):
        body.append(Paragraph(esc(item["impact"]), STYLES["TableCellMuted"]))

    table = Table([[badge, body]], colWidths=[18 * mm, 148 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), severity_color(severity)),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                ("BACKGROUND", (1, 0), (1, 0), SURFACE_SUNKEN),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _render_action_plan(payload: ReportPayload) -> List[Flowable]:
    plan = payload.action_plan
    if not plan:
        return []

    sections: List[Flowable] = []
    for title, attr in _HORIZONS:
        steps = getattr(plan, attr, None)
        if steps:
            sections.extend(_render_horizon(title, steps))

    if not sections:
        return []
    return [Paragraph("Action Plan", STYLES["H1"]), *sections, Spacer(1, 8)]


def _render_horizon(title: str, steps: Iterable[dict]) -> List[Flowable]:
    flowables: List[Flowable] = [Paragraph(title, STYLES["H2"])]
    for index, step in enumerate(steps, start=1):
        label = f"<b>{index}.</b> {esc(step.get('step', ''))}"
        meta_bits = [b for b in (step.get("module"), step.get("effort")) if b]
        flowables.append(Paragraph(label, STYLES["ListItem"]))
        if meta_bits:
            flowables.append(Paragraph(esc(" · ".join(meta_bits)), STYLES["ListItemMeta"]))
    return flowables
