"""
pdf/scoring.py

"How the scores work": a short closing page that explains what the 0-100
numbers mean, the overall calculation for this audit (with its real
module scores) and how each module's score is built. The numbers come
from the same constants the scoring code uses, so the explanation cannot
drift from the scores.
"""

from __future__ import annotations

from typing import List

from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Flowable, Paragraph, Spacer, Table, TableStyle

from config.constants import DEFAULT_MODULE_WEIGHT, MODULE_WEIGHTS
from consent.consent_score import SEVERITY_PENALTY
from pdf.components import CONTENT_WIDTH, section_intro
from pdf.theme import (BORDER, ERROR_SOFT, ERROR_TEXT, STYLES, SUCCESS_SOFT, SUCCESS_TEXT, SURFACE_SUNKEN,
                       WARNING_SOFT, WARNING_TEXT, esc, hexstr)
from reports.generator import ReportPayload

W = CONTENT_WIDTH

CONSENT_AREAS = [
    ("Cookie banner is present", 25), ("Tracking is really held back until consent", 20),
    ("Live click test (Accept / Reject in a real browser)", 20), ("Accept / Reject / Settings buttons", 15),
    ("Cookies set before consent", 15), ("Network requests before consent", 10),
    ("Preference centre / changing your choice later", 10), ("Google Consent Mode", 5),
]
ANALYTICS_AREAS = [
    ("Google Analytics 4", 15), ("Google Tag Manager", 15), ("Data layer", 15), ("Adobe Analytics", 10),
    ("Meta Pixel", 10), ("Duplicate tags", 10),
    ("Piano, Microsoft Clarity, Hotjar, LinkedIn, TikTok and other tags", 5),
]


def _weight(module: str) -> int:
    return int(round(100 * MODULE_WEIGHTS.get(module, DEFAULT_MODULE_WEIGHT)))


def overall_calculation(payload: ReportPayload) -> str:
    """'(Consent 98 × 20 + Analytics 77 × 15) ÷ 35 = 89/100' for this audit."""
    cells = [c for c in payload.score_grid if c.score is not None]
    if not cells:
        return ""
    if len(cells) == 1:
        return f"Only {cells[0].label} was scored, so the overall score is {int(cells[0].score)}/100."
    parts = [f"{c.label} {int(c.score)} × {_weight(c.module)}" for c in cells]
    total = sum(_weight(c.module) for c in cells)
    return f"({' + '.join(parts)}) ÷ {total} = {payload.overall}/100"


def _bands() -> Table:
    style = STYLES["Body"].clone("sc_band", fontSize=9, leading=12, spaceAfter=0)
    cells = [
        Paragraph(f'<font color="{hexstr(SUCCESS_TEXT)}"><b>80–100 · Healthy</b></font>', style),
        Paragraph(f'<font color="{hexstr(WARNING_TEXT)}"><b>50–79 · Needs attention</b></font>', style),
        Paragraph(f'<font color="{hexstr(ERROR_TEXT)}"><b>0–49 · Issues found</b></font>', style),
    ]
    t = Table([cells], colWidths=[(W - 8 * mm) / 3] * 3, spaceBefore=2 * mm, spaceAfter=2 * mm)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), SUCCESS_SOFT), ("BACKGROUND", (1, 0), (1, 0), WARNING_SOFT),
        ("BACKGROUND", (2, 0), (2, 0), ERROR_SOFT),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
    ]))
    return t


def _weights_table(rows: List[tuple]) -> Table:
    td = STYLES["Body"].clone("sc_td", fontSize=8.5, leading=11, spaceAfter=0)
    data = [[Paragraph(esc(name), td), Paragraph(f"<b>{w}</b>", td.clone("sc_tdr", alignment=2))] for name, w in rows]
    t = Table(data, colWidths=[W - 22 * mm, 22 * mm])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.3 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.3 * mm),
    ]))
    return t


def build_scoring_flowables(payload: ReportPayload) -> List[Flowable]:
    if not payload.score_grid:
        return []
    body = STYLES["Body"]
    small = STYLES["Small"]
    h2 = STYLES["H2"]
    modules = {c.module for c in payload.score_grid}
    crit, warn, info = (SEVERITY_PENALTY["critical"], SEVERITY_PENALTY["warning"], SEVERITY_PENALTY["info"])

    story: List[Flowable] = []
    story += section_intro(
        "Reading this report", "How the scores work",
        "Every score is a <b>health rating out of 100, not a percentage</b>. 100 means no problems were found; "
        "points are taken off for each problem, and more for serious ones. A score of 77 does not mean "
        "“77% compliant” or “77% of checks passed”.")
    story.append(_bands())

    calc = overall_calculation(payload)
    if calc:
        story.append(Paragraph("This audit’s overall score", h2))
        story.append(Paragraph(
            "A weighted average of the modules that ran. Consent counts a little more because it is "
            "checked with a real browser and carries legal risk.", body))
        t = Table([[Paragraph(esc(calc), body.clone("sc_calc", fontName="Courier-Bold", fontSize=9, spaceAfter=0))]],
                  colWidths=[W])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SURFACE_SUNKEN),
                               ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm), ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm)]))
        story.append(t)

    if modules & {"consent", "analytics"}:
        story.append(CondPageBreak(45 * mm))
        story.append(Paragraph("Consent and Analytics scores", h2))
        story.append(Paragraph(
            "Each module is split into areas. Every area starts at 100 and loses points for each issue found in it "
            f"(never below 0): <b>Critical −{crit}</b>, <b>Warning −{warn}</b>, <b>Info −{info}</b>. The module score is the "
            "weighted average of its areas, so the areas that matter most count most. A tool that isn’t on the site "
            "has no issues, so its area stays at 100.", body))
        if "consent" in modules:
            story.append(CondPageBreak(40 * mm))
            story.append(Paragraph("Consent areas (relative weight)", STYLES["H3"]))
            story.append(_weights_table(CONSENT_AREAS))
            story.append(Spacer(1, 3 * mm))
        if "analytics" in modules:
            story.append(CondPageBreak(36 * mm))
            story.append(Paragraph("Analytics areas (relative weight)", STYLES["H3"]))
            story.append(_weights_table(ANALYTICS_AREAS))
            story.append(Spacer(1, 3 * mm))

    if "journey" in modules:
        story.append(CondPageBreak(30 * mm))
        story.append(Paragraph("Journey Map score", h2))
        story.append(Paragraph(
            "Journey Health is built from what happened when AuditPulse safely clicked the site’s buttons, links and "
            "forms: <b>45%</b> conversion clicks and forms picked up by analytics, <b>35%</b> interactions that worked "
            "when clicked, <b>20%</b> interactions with screenshot evidence. If nothing could be tested it shows "
            "“Not scored” instead of 0.", body))

    story.append(CondPageBreak(20 * mm))
    story.append(Paragraph("Cookie Scanner and issue counts", h2))
    story.append(Paragraph(
        "The Cookie Scanner has no score of its own: it is the full list of cookies found. Cookies set before "
        "consent already lower the Consent score. The Critical / Warning / Info counts are distinct issues; the "
        "same problem on many pages counts once.", body))
    story.append(Paragraph("Weights and deductions are the same for every audit, so scores can be compared over time.",
                           small))
    return story
