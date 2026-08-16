"""
pdf/recommendations.py

Renders the two AI-generated "what to do about it" sections from
reports/generator.py's ReportPayload:

  - Business Impact (ai/business_impact.py) — why each problem matters,
    in plain-business terms, now cross-referenced back to the finding it
    came from (§3.7 / Table 6: "Add finding IDs ... Group repeated
    recommendations").
  - Action Plan (ai/action_plan.py) — the same findings regrouped into
    quick_wins / short_term / long_term horizons, presented as a
    Priority / Finding ID / Module / Recommended Action table per
    horizon, with duplicate remediations (e.g. five identical contrast
    fixes) collapsed into one row plus an affected-item count (§3.8:
    "Do not repeat the same contrast recommendation for every selector;
    group the recommendation and show the affected selectors/count
    separately").

Neither `ai/business_impact.py` nor `ai/action_plan.py` attaches a
Finding ID to its own output (that field only exists on
`payload.findings`, assigned by reports/generator.py's
`assign_finding_ids`), so this module matches items back to their
originating finding by (title, module) — the same natural key
pdf/summary.py's grouping uses — rather than re-deriving IDs of its own,
so a finding's ID is always the one `payload.findings` already assigned
to it (§9/§11: one canonical source, never a second one invented here).

Mirrors reports/html_report.py's `_render_business_impact` /
`_render_action_plan`, just as PDF flowables instead of HTML strings.
Both sections are additive/optional on the payload (`include_ai=False`
callers get neither), so each builder here returns [] when its input is
empty rather than printing an empty heading.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, Iterable, List, Tuple

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from pdf.theme import BORDER, STYLES, SURFACE_SUNKEN, esc, severity_color
from reports.generator import ReportPayload

_HORIZONS = (
    ("Phase 1 \u2013 Immediate / High Priority Actions", "quick_wins"),
    ("Phase 2 \u2013 Short-Term Actions", "short_term"),
    ("Phase 3 \u2013 Optimization Actions", "long_term"),
)

# ai/priority.py's deterministic effort estimate, shown as the plain-English
# Priority column the docx asks for (§3.8) instead of the raw effort key.
_PRIORITY_LABELS = {"critical": "Critical", "warning": "Warning", "info": "Info"}


def build_recommendations_flowables(payload: ReportPayload) -> List[Flowable]:
    flowables: List[Flowable] = []
    flowables.extend(_render_business_impact(payload))
    flowables.extend(_render_action_plan(payload))
    return flowables


def _finding_lookup(payload: ReportPayload) -> Dict[Tuple[str, str], dict]:
    """(title, module) -> the first matching finding on the payload, so a Business
    Impact item or Action Plan step can be traced back to its real Finding ID
    without this module inventing one of its own."""
    lookup: Dict[Tuple[str, str], dict] = {}
    for finding in payload.findings:
        key = (finding.get("title", ""), finding.get("module", ""))
        lookup.setdefault(key, finding)
    return lookup


def _find_finding_id(lookup: Dict[Tuple[str, str], dict], title: str, module: str = "") -> str:
    """Exact (title, module) match first; falls back to a title-only match for
    callers (e.g. business_impact items) that don't carry a module of their own."""
    if module:
        finding = lookup.get((title, module))
        if finding:
            return finding.get("finding_id", "")
    for (t, _m), finding in lookup.items():
        if t == title:
            return finding.get("finding_id", "")
    return ""


# --------------------------------------------------------------------------
# Business Impact (§3.7)
# --------------------------------------------------------------------------

def _render_business_impact(payload: ReportPayload) -> List[Flowable]:
    if not payload.business_impact:
        return []

    lookup = _finding_lookup(payload)
    flowables: List[Flowable] = [Paragraph("Business Impact", STYLES["H1"])]
    for item in payload.business_impact:
        finding_id = _find_finding_id(lookup, item.get("title", ""))
        flowables.append(_impact_row(item, finding_id))
    flowables.append(Spacer(1, 8))
    return flowables


def _impact_row(item: dict, finding_id: str) -> Table:
    severity = item.get("severity", "info")
    badge = Paragraph(esc(severity.upper()), STYLES["Badge"])
    title_line = f"<b>{esc(item.get('title', ''))}</b>"
    if finding_id:
        title_line += f"  <font color='#2563EB' size='7'>[{esc(finding_id)}]</font>"
    title_line += f"<font color='#64748B'>  &middot;  {esc(item.get('affected_area', ''))}</font>"
    body = [Paragraph(title_line, STYLES["TableCell"])]
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


# --------------------------------------------------------------------------
# Phased Action Plan (§3.8)
# --------------------------------------------------------------------------

def _render_action_plan(payload: ReportPayload) -> List[Flowable]:
    plan = payload.action_plan
    if not plan:
        return []

    lookup = _finding_lookup(payload)
    sections: List[Flowable] = []
    for title, attr in _HORIZONS:
        steps = getattr(plan, attr, None)
        if steps:
            sections.extend(_render_horizon(title, steps, lookup))

    if not sections:
        return []
    return [Paragraph("Action Plan", STYLES["H1"]), *sections, Spacer(1, 8)]


def _group_steps(steps: Iterable[dict]) -> List[Dict]:
    """Collapses action-plan steps that share the same (title, module) so an
    identical recommendation repeated for every affected selector becomes one
    row plus an affected-item count (§3.8), instead of N near-identical lines."""
    groups: "OrderedDict[tuple, Dict]" = OrderedDict()
    for step in steps:
        key = (step.get("title", ""), step.get("module", ""))
        if key not in groups:
            groups[key] = {
                "title": step.get("title", ""),
                "module": step.get("module", ""),
                "severity": step.get("severity", "info"),
                "step": step.get("step", ""),
                "count": 0,
            }
        groups[key]["count"] += 1
    return list(groups.values())


def _render_horizon(title: str, steps: Iterable[dict], lookup: Dict[Tuple[str, str], dict]) -> List[Flowable]:
    groups = _group_steps(steps)

    header = ["Priority", "Finding ID", "Module", "Recommended Action"]
    rows: List[list] = [header]
    priority_rows: List[tuple] = []

    for row_index, group in enumerate(groups, start=1):
        finding_id = _find_finding_id(lookup, group["title"], group["module"])
        action_text = f"<b>{esc(group['title'])}</b>: {esc(group['step'])}"
        if group["count"] > 1:
            action_text += f"  <font color='#64748B'>(affects {group['count']} items)</font>"
        rows.append([
            Paragraph(esc(_PRIORITY_LABELS.get(group["severity"], group["severity"].title())), STYLES["TableCell"]),
            Paragraph(esc(finding_id) if finding_id else "\u2014", STYLES["TableCellMuted"]),
            Paragraph(esc((group["module"] or "").replace("_", " ").title() or "General"), STYLES["TableCellMuted"]),
            Paragraph(action_text, STYLES["TableCell"]),
        ])
        priority_rows.append((row_index, group["severity"]))

    table = Table(rows, colWidths=[22 * mm, 22 * mm, 26 * mm, 94 * mm], repeatRows=1)
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
    for row_index, severity in priority_rows:
        style.append(("TEXTCOLOR", (0, row_index), (0, row_index), severity_color(severity)))
        style.append(("FONTNAME", (0, row_index), (0, row_index), "Helvetica-Bold"))
    table.setStyle(TableStyle(style))

    return [Paragraph(title, STYLES["H2"]), table, Spacer(1, 8)]
