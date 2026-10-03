"""
pdf/cover.py

Page 1: a coloured header band (drawn on the canvas — see draw_cover_band)
with the site, date, scope and the overall score ring, then an
"At a glance" block underneath built from flowables:

  * one card per audited module (icon, score, bar, status)
  * how many issues need fixing now / soon / are good to know
  * the plain-language summary

The goal is that a reader who only looks at page 1 knows how the site did
and where the problems are.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, PageBreak, Paragraph, Spacer, Table, TableStyle

from pdf.components import CONTENT_WIDTH, Bar, ScoreRing, hostname, module_icon, pill
from pdf.issues import Issue, issue_counts
from pdf.theme import (
    BORDER,
    FONT_BODY,
    FONT_BOLD,
    FONT_SEMIBOLD,
    PAGE_MARGIN_MM,
    PRIMARY,
    PRIMARY_DARK,
    SCORE_BAND_LABELS,
    SEVERITY_META,
    STYLES,
    TEXT_TERTIARY,
    WHITE,
    esc,
    hexstr,
    score_band,
    score_color,
    score_soft_color,
    score_text_color,
)
from reports.generator import ReportPayload

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
BAND_HEIGHT = 112 * mm


def _nice_date(iso: str) -> str:
    from datetime import datetime

    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %B %Y").lstrip("0")
    except ValueError:
        return iso[:10]


def draw_cover_band(canvas: Canvas, payload: ReportPayload) -> None:
    """The indigo header band: brand, site, meta and the overall score ring."""
    width, height = A4
    margin = PAGE_MARGIN_MM * mm
    top = height
    bottom = height - BAND_HEIGHT

    canvas.saveState()
    clip = canvas.beginPath()
    clip.rect(0, bottom, width, BAND_HEIGHT)
    canvas.clipPath(clip, stroke=0, fill=0)
    canvas.linearGradient(0, bottom, width, top, (PRIMARY_DARK, PRIMARY), extend=True)
    # soft decorative circles
    canvas.setFillColor(WHITE, alpha=0.06)
    canvas.circle(width - 30 * mm, top - 6 * mm, 52 * mm, stroke=0, fill=1)
    canvas.setFillColor(WHITE, alpha=0.04)
    canvas.circle(width - 8 * mm, bottom + 8 * mm, 34 * mm, stroke=0, fill=1)

    # brand
    y_brand = top - margin - 8 * mm
    x = margin
    if LOGO_PATH.is_file():
        canvas.setFillColor(WHITE)
        canvas.roundRect(x, y_brand - 1.5 * mm, 11 * mm, 11 * mm, 2.4 * mm, stroke=0, fill=1)
        try:
            canvas.drawImage(str(LOGO_PATH), x + 1 * mm, y_brand - 0.5 * mm, 9 * mm, 9 * mm,
                             mask="auto", preserveAspectRatio=True)
        except Exception:  # noqa: BLE001
            pass
        x += 14 * mm
    canvas.setFillColor(WHITE)
    canvas.setFont(FONT_BOLD, 13)
    canvas.drawString(x, y_brand + 4.2 * mm, "AuditPulse")
    canvas.setFillColor(WHITE, alpha=0.72)
    canvas.setFont(FONT_BODY, 8.5)
    canvas.drawString(x, y_brand, "Website Health AI")

    # title block
    host = hostname(payload.url)
    canvas.setFillColor(WHITE, alpha=0.78)
    canvas.setFont(FONT_SEMIBOLD, 10.5)
    canvas.drawString(margin, top - 50 * mm, "Website audit report")
    canvas.setFillColor(WHITE)
    size = 30 if len(host) <= 22 else 24 if len(host) <= 30 else 19
    canvas.setFont(FONT_BOLD, size)
    canvas.drawString(margin, top - 62 * mm, host)
    canvas.setFillColor(WHITE, alpha=0.78)
    canvas.setFont(FONT_BODY, 9.5)
    canvas.drawString(margin, top - 69 * mm, _clip(payload.url, 70))

    modules = ", ".join(c.label for c in payload.score_grid) or "—"
    meta = [("Audit date", _nice_date(payload.generated_at) or "—"),
            ("Audit ID", f"#{payload.audit_id}"),
            ("Checked", modules)]
    mx = margin
    for label, value in meta:
        canvas.setFillColor(WHITE, alpha=0.62)
        canvas.setFont(FONT_SEMIBOLD, 7.5)
        canvas.drawString(mx, top - 84 * mm, label)
        canvas.setFillColor(WHITE)
        canvas.setFont(FONT_SEMIBOLD, 9.5)
        canvas.drawString(mx, top - 89 * mm, _clip(value, 46))
        mx += max(30 * mm, canvas.stringWidth(value, FONT_SEMIBOLD, 9.5) + 10 * mm)

    # score ring
    ring_size = 44 * mm
    rx = width - margin - ring_size
    ry = top - 92 * mm
    canvas.setFillColor(WHITE, alpha=0.10)
    canvas.circle(rx + ring_size / 2, ry + ring_size / 2, ring_size / 2 + 4 * mm, stroke=0, fill=1)
    ring = ScoreRing(payload.overall, size=ring_size, stroke=3.6 * mm, on_dark=True, label="overall score")
    ring.canv = canvas
    canvas.saveState()
    canvas.translate(rx, ry)
    ring.draw()
    canvas.restoreState()
    status = SCORE_BAND_LABELS[score_band(payload.overall)]
    canvas.setFont(FONT_SEMIBOLD, 9)
    tw = canvas.stringWidth(status, FONT_SEMIBOLD, 9) + 8 * mm
    px = rx + ring_size / 2 - tw / 2
    py = ry - 9 * mm
    canvas.setFillColor(WHITE)
    canvas.roundRect(px, py, tw, 6 * mm, 3 * mm, stroke=0, fill=1)
    canvas.setFillColor(score_text_color(payload.overall))
    canvas.drawCentredString(rx + ring_size / 2, py + 1.9 * mm, status)
    canvas.restoreState()


def draw_cover_footer(canvas: Canvas) -> None:
    width, _ = A4
    canvas.saveState()
    canvas.setFont(FONT_SEMIBOLD, 8)
    canvas.setFillColor(TEXT_TERTIARY)
    canvas.drawCentredString(width / 2, 10 * mm, "Designed by Jeevan K S")
    canvas.restoreState()


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


# --------------------------------------------------------------------------
# Flowables below the band
# --------------------------------------------------------------------------
def _module_card(cell, width: float) -> Table:
    score = int(cell.score)
    status = SCORE_BAND_LABELS[score_band(score)]
    head = Table(
        [[module_icon(cell.module, 8.5 * mm),
          Paragraph(esc(cell.label), STYLES["H3"].clone("mc_l", spaceAfter=0))]],
        colWidths=[11 * mm, width - 11 * mm - 8 * mm],
    )
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    score_p = Paragraph(
        f'<font color="{hexstr(score_color(score))}">{score}</font>'
        f'<font size="9" color="{hexstr(TEXT_TERTIARY)}" name="{FONT_BODY}"> / 100</font>',
        STYLES["Stat"].clone("mc_s", fontSize=24, leading=27),
    )
    status_p = pill(status, score_text_color(score), score_soft_color(score), width=None)
    status_p.hAlign = "LEFT"
    inner = width - 8 * mm
    t = Table([[head], [score_p], [Bar(score, inner, 2.2 * mm)], [status_p]],
              colWidths=[width], cornerRadii=[7, 7, 7, 7])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, 0), 4 * mm),
        ("TOPPADDING", (0, 1), (-1, 1), 2.5 * mm),
        ("TOPPADDING", (0, 2), (-1, 2), 1 * mm),
        ("TOPPADDING", (0, 3), (-1, 3), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 4 * mm),
    ]))
    return t


def _row(cells: List[Flowable], width: float, gap: float = 4 * mm) -> Table:
    n = len(cells)
    w = (width - gap * (n - 1)) / n
    row, widths = [], []
    for i, c in enumerate(cells):
        row.append(c)
        widths.append(w)
        if i < n - 1:
            row.append("")
            widths.append(gap)
    t = Table([row], colWidths=widths)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _severity_tile(sev: str, count: int, width: float) -> Table:
    meta = SEVERITY_META[sev]
    t = Table(
        [[Paragraph(f'<font color="{hexstr(meta["text"])}">{count}</font>', STYLES["Stat"].clone("sv_n", fontSize=22, leading=25)),
          [Paragraph(esc(meta["action"]), STYLES["H3"].clone("sv_a", spaceAfter=0, textColor=meta["text"])),
           Paragraph(f'{esc(meta["label"])} issue{"s" if count != 1 else ""}', STYLES["Small"])]]],
        colWidths=[19 * mm, width - 19 * mm], cornerRadii=[7, 7, 7, 7],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), meta["bg"]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6 * mm),
    ]))
    return t


def build_cover_flowables(payload: ReportPayload, issues: List[Issue], has_appendix: bool = True) -> List[Flowable]:
    width = CONTENT_WIDTH
    story: List[Flowable] = [Paragraph("At a glance", STYLES["H2"].clone("ag", spaceBefore=0, spaceAfter=3 * mm))]

    if payload.score_grid:
        cards = [_module_card(c, (width - 8 * mm) / 3) for c in payload.score_grid[:3]]
        while len(cards) < 3:
            cards.append(Spacer(1, 1))
        story.append(_row(cards, width))
        story.append(Spacer(1, 4 * mm))

    counts = issue_counts(issues)
    tiles = [_severity_tile(s, counts[s], (width - 8 * mm) / 3) for s in ("critical", "warning", "info")]
    story.append(_row(tiles, width))
    total = len(payload.findings or [])
    story.append(Paragraph(
        f"{len(issues)} distinct issue{'s' if len(issues) != 1 else ''} to review, grouped from {total} raw "
        f"finding{'s' if total != 1 else ''} (the same problem on many pages counts once).",
        STYLES["Small"].clone("ag_note", spaceBefore=2 * mm)))

    if payload.executive_summary:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Summary", STYLES["H2"].clone("sum_h", spaceBefore=0)))
        story.append(Paragraph(esc(payload.executive_summary), STYLES["Body"].clone("sum_b", fontSize=10, leading=15)))

    contents = ["Start here — what to fix first"]
    for c in payload.score_grid:
        contents.append({"consent": "Consent & cookies — banner, screenshots, what loads before consent",
                         "analytics": "Analytics & tracking — tools found and the live browser check",
                         "journey": "Customer journey — buttons, forms and downloads we tested, with screenshots"}.get(c.module, c.label))
    if has_appendix:
        contents.append("Appendix — full lists and scan details")
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("In this report", STYLES["H2"].clone("toc_h", spaceBefore=0)))
    for i, line in enumerate(contents, 1):
        title, _, rest = line.partition(" — ")
        story.append(Paragraph(
            f'<font color="{hexstr(PRIMARY)}" name="{FONT_SEMIBOLD}">{i}</font>&nbsp;&nbsp;&nbsp;'
            f'<font name="{FONT_SEMIBOLD}">{esc(title)}</font>'
            + (f'<font color="{hexstr(TEXT_TERTIARY)}"> — {esc(rest)}</font>' if rest else ""),
            STYLES["Body"].clone("toc_i", spaceAfter=1.6 * mm)))

    story.append(PageBreak())
    return story
