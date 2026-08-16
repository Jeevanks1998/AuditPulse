"""
pdf/summary.py

Phase 2 (Professional Content Structure): renders "Executive Summary"
(target structure §2 item 3) and, as a separate section, "Critical
Findings" (item 6) — mirroring reports/html_report.py's `_render_summary`
but restructured around real, already-computed payload fields instead of
a single prose block plus an undifferentiated priorities table.

Executive Summary now carries:
  - the existing AI/deterministic summary prose (§3.3: "Keep the existing
    AI/deterministic executive summary as the source of prose" — this
    module never rewrites or re-derives that text, only lays it out).
  - four metric cards (Overall Score, Critical Findings, Total Findings,
    Weakest Module) plus an Overall Status label, all read straight off
    `payload.severity_counts` / `payload.weakest_module` /
    `payload.overall_status` — reports/generator.py's single derived
    source for these (§9/§11), never recomputed here.
  - a short "Key Areas Requiring Attention" list built from the real
    critical/warning findings (grouped so a repeated issue — e.g. five
    contrast failures — contributes one line, not five).

Critical Findings groups same-title/same-module findings together
(§3.6: "Group repeated findings with the same title/module where
appropriate"), shows each group's Finding ID and, where more than one
finding was grouped, how many items it affects — the technical detail for
every individual instance still lives in the appendix (pdf/appendix.py),
this section only summarizes.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle

from pdf.theme import BORDER, STYLES, SURFACE_SUNKEN, esc, severity_color
from reports.generator import ReportPayload

_MAX_KEY_AREAS = 6


def build_summary_flowables(payload: ReportPayload) -> List[Flowable]:
    """Returns the "Executive Summary" section: prose, metric cards, status, and
    a short key-areas list. Critical Findings is a separate section — see
    `build_critical_findings_flowables` below — so it gets its own TOC entry."""
    flowables: List[Flowable] = []
    flowables.extend(_render_executive_summary(payload))
    flowables.extend(_render_metric_cards(payload))
    flowables.extend(_render_key_areas(payload))
    return flowables


def build_critical_findings_flowables(payload: ReportPayload) -> List[Flowable]:
    """Returns the dedicated "Critical Findings" section, or [] if none were found."""
    critical = [f for f in payload.findings if f.get("severity") == "critical"]
    if not critical:
        return []

    groups = _group_findings(critical)

    header = ["Finding ID", "Module", "Finding", "Affects"]
    rows: List[list] = [header]
    for group in groups:
        title_cell = [Paragraph(f"<b>{esc(group['title'])}</b>", STYLES["TableCell"])]
        if group["description"]:
            title_cell.append(Paragraph(esc(group["description"]), STYLES["TableCellMuted"]))
        affects = f"{group['count']} item(s)" if group["count"] > 1 else "1 item"
        rows.append([
            Paragraph(esc(group["finding_id"]), STYLES["TableCell"]),
            Paragraph(esc(group["module_label"]), STYLES["TableCellMuted"]),
            title_cell,
            Paragraph(esc(affects), STYLES["TableCellMuted"]),
        ])

    table = Table(rows, colWidths=[24 * mm, 26 * mm, 94 * mm, 20 * mm], repeatRows=1)
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
    for row_index in range(1, len(rows)):
        style.append(("TEXTCOLOR", (0, row_index), (0, row_index), severity_color("critical")))
        style.append(("FONTNAME", (0, row_index), (0, row_index), "Helvetica-Bold"))
    table.setStyle(TableStyle(style))

    grouped_note = (
        f"{len(critical)} critical finding(s) grouped into {len(groups)} distinct issue(s)."
        if len(critical) != len(groups)
        else f"{len(critical)} critical finding(s)."
    )

    return [
        Paragraph("Critical Findings", STYLES["H1"]),
        Paragraph(grouped_note, STYLES["BodyMuted"]),
        Spacer(1, 4),
        table,
        Spacer(1, 10),
    ]


# --------------------------------------------------------------------------
# Executive Summary building blocks
# --------------------------------------------------------------------------

def _render_executive_summary(payload: ReportPayload) -> List[Flowable]:
    if not payload.executive_summary:
        return []
    flowables: List[Flowable] = [
        Paragraph("Executive Summary", STYLES["H1"]),
        Paragraph(esc(payload.executive_summary), STYLES["Body"]),
    ]
    if payload.overall_status:
        flowables.append(Paragraph(f"Overall Status: <b>{esc(payload.overall_status)}</b>", STYLES["Body"]))
    flowables.append(Spacer(1, 8))
    return flowables


def _render_metric_cards(payload: ReportPayload) -> List[Flowable]:
    """Overall Score / Critical Findings / Total Findings / Weakest Module (§3.3) —
    four real numbers read straight off the payload, no independent counting."""
    critical_count = (payload.severity_counts or {}).get("critical", 0)
    total_count = len(payload.findings)
    weakest = payload.weakest_module

    cards = [
        ("Overall Score", f"{payload.overall}/100"),
        ("Critical Findings", str(critical_count)),
        ("Total Findings", str(total_count)),
        ("Weakest Module", f"{weakest.label} ({weakest.score}/100)" if weakest else "N/A"),
    ]

    cells = []
    for label, value in cards:
        value_style = STYLES["MetricValue"] if len(value) <= 8 else STYLES["MetricValueSmall"]
        cell = Table(
            [[Paragraph(esc(value), value_style)], [Paragraph(esc(label).upper(), STYLES["MetricLabel"])]],
            colWidths=[40 * mm],
        )
        cell.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
            ("BACKGROUND", (0, 0), (-1, -1), SURFACE_SUNKEN),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        cells.append(cell)

    row = Table([cells], colWidths=[42 * mm] * 4)
    row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return [row, Spacer(1, 10)]


def _render_key_areas(payload: ReportPayload) -> List[Flowable]:
    """"Key Areas Requiring Attention" (§3.3) — a short, deduplicated list of the
    real critical/warning finding titles, worst first. Never invented: every line
    is a real finding's title, grouped so a repeated issue counts once."""
    notable = [f for f in payload.findings if f.get("severity") in ("critical", "warning")]
    if not notable:
        return []

    groups = _group_findings(notable)[:_MAX_KEY_AREAS]
    if not groups:
        return []

    items: List[Flowable] = [Paragraph("Key Areas Requiring Attention", STYLES["H2"])]
    for group in groups:
        suffix = f" ({group['count']} instances)" if group["count"] > 1 else ""
        items.append(Paragraph(
            f"&bull; <b>{esc(group['title'])}</b> &mdash; {esc(group['module_label'])}{esc(suffix)}",
            STYLES["ListItem"],
        ))
    items.append(Spacer(1, 8))
    return items


# --------------------------------------------------------------------------
# Shared grouping helper
# --------------------------------------------------------------------------

def _group_findings(findings: List[dict]) -> List[Dict]:
    """Collapses findings that share the same (title, module) into one group
    (§3.6 / Table 4: "Do not repeat identical contrast findings as separate
    priority recommendations"), preserving first-seen order (severity/module
    order is already established by the caller) and the representative
    Finding ID of the first occurrence in each group.
    """
    groups: "OrderedDict[tuple, Dict]" = OrderedDict()
    for finding in findings:
        key = (finding.get("title", ""), finding.get("module", ""))
        if key not in groups:
            groups[key] = {
                "title": finding.get("title", ""),
                "module_label": (finding.get("module") or "").replace("_", " ").title() or "General",
                "description": finding.get("description", ""),
                "finding_id": finding.get("finding_id", ""),
                "severity": finding.get("severity", "info"),
                "count": 0,
            }
        groups[key]["count"] += 1
    return list(groups.values())
