"""
pdf/overview.py

Page 2 — "Start here": the five things to fix first (one line each, with
where to look), what was checked, and a short key explaining the colours
and labels used through the rest of the report.
"""

from __future__ import annotations

from typing import List

from reportlab.lib.units import mm
from reportlab.platypus import Flowable, KeepTogether, Paragraph, Spacer, Table, TableStyle

from pdf.components import CONTENT_WIDTH, card, hostname, pill, section_intro, soft_wrap, stat_tiles
from pdf.issues import Issue
from pdf.theme import (
    BORDER,
    FONT_SEMIBOLD,
    MODULE_LABELS,
    SCORE_BAND_GOOD,
    SCORE_BAND_MID,
    SEVERITY_META,
    STYLES,
    SUCCESS_SOFT,
    SUCCESS_TEXT,
    TEXT_SECONDARY,
    TEXT_TERTIARY,
    WARNING_SOFT,
    WARNING_TEXT,
    ERROR_SOFT,
    ERROR_TEXT,
    WHITE,
    esc,
    hexstr,
    module_color,
)
from reports.generator import ReportPayload

TOP_N = 5


def _first_sentence(text: str, limit: int = 170) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    import re as _re
    for m in _re.finditer(r"\.\s", text):
        before = text[max(0, m.start() - 4): m.start() + 1].lower()
        if before.endswith(("e.g.", "i.e.", "etc.", "vs.")):
            continue
        if m.start() < limit:
            return text[: m.start() + 1]
        break
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _top_row(issue: Issue, n: int, width: float) -> Table:
    meta = SEVERITY_META[issue.severity]
    fg, _ = module_color(issue.module)
    where = ""
    if issue.count > 1:
        where = f" · {issue.count}× ({len(issue.items) or issue.count} places)"
    elif issue.items:
        where = " · " + soft_wrap(issue.items[0])
    title = esc(issue.title)
    if issue.count == 1 and getattr(issue, "_subject_titled", False) and issue.items:
        title += ": " + soft_wrap(issue.items[0].split(" — on ")[0])
        where = ""
    fix = _first_sentence(issue.recommendation)
    body = [
        Paragraph(title, STYLES["H3"].clone("tr_t", spaceAfter=1)),
        Paragraph(
            f'<font name="{FONT_SEMIBOLD}" color="{hexstr(fg)}">{esc(MODULE_LABELS.get(issue.module, issue.module.title()))}</font>'
            f'<font color="{hexstr(TEXT_TERTIARY)}">{where}</font>', STYLES["Small"]),
    ]
    if fix:
        body.append(Paragraph(f'<font color="{hexstr(TEXT_SECONDARY)}">How to fix:</font> {soft_wrap(fix)}',
                              STYLES["Small"].clone("tr_f", spaceBefore=1.5, textColor=STYLES["Body"].textColor)))
    num = Table([[Paragraph(f'<font color="white">{n}</font>', STYLES["Center"].clone("tr_n", fontName=FONT_SEMIBOLD, fontSize=10, leading=12))]],
                colWidths=[7 * mm], rowHeights=[7 * mm], cornerRadii=[3.5 * mm] * 4)
    num.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), meta["fg"]), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                             ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    t = Table([[num, body, pill(meta["action"], meta["text"], meta["bg"], width=22 * mm)]],
              colWidths=[11 * mm, width - 11 * mm - 25 * mm, 25 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, BORDER),
    ]))
    return t


def _scope_tiles(payload: ReportPayload) -> List[tuple]:
    tiles = []
    jv = payload.journey_view or {}
    counts = jv.get("counts") or {}
    an = payload.analytics or {}
    cov = an.get("site_coverage") or {}
    pages = counts.get("pages_scanned") or cov.get("pages_scanned")
    if pages:
        tiles.append((pages, "Pages scanned"))
    if counts.get("interactions_tested") is not None and jv.get("available"):
        tiles.append((counts.get("interactions_tested", 0), "Buttons, links & forms tested"))
    vendors = _vendor_names(payload)
    if an:
        tiles.append((len(vendors), "Analytics / tag tools seen"))
    cv = payload.consent_view or {}
    status = cv.get("status") or {}
    if cv:
        tiles.append(("Yes" if status.get("banner_detected") else "No", "Cookie banner found"))
    return tiles[:4]


def _vendor_names(payload: ReportPayload) -> List[str]:
    an = payload.analytics or {}
    rr = an.get("runtime_result") or {}
    names = []
    for t in rr.get("observed_tags") or []:
        if t.get("vendor") and t["vendor"] not in names:
            names.append(t["vendor"])
    for t in an.get("trackers_detected") or []:
        if t not in names:
            names.append(t)
    return names


def _legend(width: float) -> Table:
    def item(pill_t, text):
        t = Table([[pill_t, Paragraph(text, STYLES["Small"])]], colWidths=[25 * mm, width / 2 - 29 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6)]))
        return t

    sev = [item(pill(m["action"], m["text"], m["bg"], width=22 * mm),
                {"critical": "Real risk now — legal exposure, broken journeys or lost data.",
                 "warning": "Hurts data quality or experience; plan it in.",
                 "info": "Worth knowing; fix when convenient."}[k])
           for k, m in SEVERITY_META.items()]
    bands = [
        item(pill(f"{SCORE_BAND_GOOD}–100", SUCCESS_TEXT, SUCCESS_SOFT, width=22 * mm), "Healthy — only small things to tidy up."),
        item(pill(f"{SCORE_BAND_MID}–{SCORE_BAND_GOOD - 1}", WARNING_TEXT, WARNING_SOFT, width=22 * mm), "Needs attention — some important gaps."),
        item(pill(f"0–{SCORE_BAND_MID - 1}", ERROR_TEXT, ERROR_SOFT, width=22 * mm), "Issues found — fix before relying on it."),
    ]
    rows = [[Paragraph("Issue labels", STYLES["Label"]), Paragraph("Scores", STYLES["Label"])]]
    for a, b in zip(sev, bands):
        rows.append([a, b])
    t = Table(rows, colWidths=[width / 2, width / 2])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return t


def build_overview_flowables(payload: ReportPayload, issues: List[Issue]) -> List[Flowable]:
    width = CONTENT_WIDTH
    story: List[Flowable] = []
    top = issues[:TOP_N]
    if top:
        story += section_intro(
            "Start here",
            "What to fix first",
            f"The {len(top)} most important issue{'s' if len(top) != 1 else ''} on {esc(hostname(payload.url))}, "
            "most urgent first. The module sections that follow show the evidence behind them.",
        )
        for n, issue in enumerate(top, 1):
            story.append(_top_row(issue, n, width))
    else:
        story += section_intro("Start here", "Nothing urgent to fix",
                               "This audit found no issues that need action.")

    tiles = _scope_tiles(payload)
    if tiles:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("What we checked", STYLES["H2"].clone("wc", spaceBefore=0)))
        story.append(stat_tiles(tiles, width))
        vendors = _vendor_names(payload)
        if vendors:
            story.append(Paragraph(
                f'<font color="{hexstr(TEXT_TERTIARY)}">Tools seen in the live browser:</font> ' + esc(", ".join(vendors[:12])),
                STYLES["Small"]))

    story.append(Spacer(1, 6 * mm))
    story.append(KeepTogether([
        Paragraph("How to read this report", STYLES["H2"].clone("hr", spaceBefore=0)),
        card([[_legend(width - 8 * mm)]], [width], background=WHITE),
    ]))
    return story
