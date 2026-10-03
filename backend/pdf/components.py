"""
pdf/components.py

Reusable building blocks for the report: pills, score ring / bars, stat
tiles, light data tables, accent cards, section headers and compressed
images. Every section module composes these so the whole PDF shares one
look (the same one as the web app).
"""

from __future__ import annotations

import io
import math
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
from urllib.parse import unquote, urlparse

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Image, KeepTogether, Paragraph, Spacer, Table, TableStyle

from pdf.theme import (
    BORDER,
    FONT_BOLD,
    FONT_BODY,
    FONT_SEMIBOLD,
    PRIMARY,
    STATE_META,
    STYLES,
    SURFACE_SUNKEN,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_TERTIARY,
    WHITE,
    esc,
    hexstr,
    module_color,
    score_color,
)

CONTENT_WIDTH = 178 * mm  # A4 width minus 2 x 16 mm margins


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------
def short_url(url: Optional[str], keep_host: bool = False, limit: int = 60) -> str:
    """Readable form of a URL: a file link becomes its file name, a page
    becomes its path ("/about-us"). Long values are shortened."""
    if not url:
        return ""
    text = str(url).strip()
    if not re.match(r"^https?://", text):
        return _ellipsis(text, limit)
    parsed = urlparse(text)
    path = unquote(parsed.path or "/")
    last = path.rstrip("/").rsplit("/", 1)[-1]
    if "." in last and len(last) > 4 and not last.endswith((".html", ".htm", ".php", ".aspx")):
        out = last  # a file: show its name
    else:
        out = path or "/"
        if out == "/" and not keep_host:
            out = "Homepage"
        if keep_host:
            out = parsed.netloc + (out if out != "/" else "")
    return _ellipsis(out, limit)


def _ellipsis(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def hostname(url: str) -> str:
    try:
        host = urlparse(url if "://" in url else "https://" + url).netloc or url
    except Exception:  # noqa: BLE001
        host = url
    return host[4:] if host.startswith("www.") else host


def soft_wrap(text: str) -> str:
    """Escaped text with zero-width break opportunities after / _ - so a long
    URL or file name wraps inside a table cell instead of overflowing."""
    return re.sub(r"([/_\-.?&=])", "\\1\u200b", esc(text))


# --------------------------------------------------------------------------
# Pills / badges
# --------------------------------------------------------------------------
def pill(text: str, fg, bg, width: Optional[float] = None, font_size: float = 7.5) -> Table:
    style = STYLES["Pill"].clone("pill_tmp", fontSize=font_size, leading=font_size + 1.5, textColor=fg)
    t = Table([[Paragraph(esc(text), style)]], colWidths=[width] if width else None, cornerRadii=[4, 4, 4, 4])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def state_pill(state: str, width: float = 20 * mm) -> Table:
    label, fg, bg = STATE_META.get(state, (state.replace("_", " ").title(), TEXT_TERTIARY, SURFACE_SUNKEN))
    return pill(label, fg, bg, width=width)


def inline_tag(text: str, fg, bg=None) -> str:
    """Coloured inline label for use inside a Paragraph."""
    return f'<font name="{FONT_SEMIBOLD}" color="{hexstr(fg)}">{esc(text)}</font>'


# --------------------------------------------------------------------------
# Score ring + bars
# --------------------------------------------------------------------------
class ScoreRing(Flowable):
    def __init__(self, score: Optional[int], size: float = 34 * mm, stroke: float = 3.2 * mm,
                 track=None, label: str = "/ 100", text_color=None, on_dark: bool = False):
        super().__init__()
        self.score = score
        self.size = size
        self.stroke = stroke
        self.track = track or (colors.Color(1, 1, 1, 0.18) if on_dark else BORDER)
        self.label = label
        self.text_color = text_color or (WHITE if on_dark else TEXT_PRIMARY)
        self.on_dark = on_dark
        self.width = self.height = size

    def draw(self):
        c = self.canv
        r = (self.size - self.stroke) / 2
        cx = cy = self.size / 2
        c.saveState()
        c.setLineWidth(self.stroke)
        c.setStrokeColor(self.track)
        c.circle(cx, cy, r, stroke=1, fill=0)
        if self.score is not None:
            c.setStrokeColor(score_color(self.score))
            c.setLineCap(1)
            extent = -360 * max(0, min(100, self.score)) / 100.0
            p = c.beginPath()
            p.arc(cx - r, cy - r, cx + r, cy + r, startAng=90, extent=extent)
            c.drawPath(p, stroke=1, fill=0)
        c.setFillColor(self.text_color)
        c.setFont(FONT_BOLD, self.size * 0.30)
        c.drawCentredString(cx, cy - self.size * 0.06, "—" if self.score is None else str(self.score))
        c.setFont(FONT_BODY, self.size * 0.095)
        c.setFillColor(colors.Color(1, 1, 1, 0.75) if self.on_dark else TEXT_TERTIARY)
        c.drawCentredString(cx, cy - self.size * 0.22, self.label)
        c.restoreState()


class Bar(Flowable):
    """A horizontal progress bar (0-100)."""

    def __init__(self, value: Optional[float], width: float, height: float = 2.4 * mm, color=None, track=None):
        super().__init__()
        self.value = value
        self.width = width
        self.height = height
        self.color = color
        self.track = track or BORDER

    def draw(self):
        c = self.canv
        r = self.height / 2
        c.setFillColor(self.track)
        c.roundRect(0, 0, self.width, self.height, r, stroke=0, fill=1)
        if self.value:
            w = max(self.height, self.width * max(0, min(100, self.value)) / 100.0)
            c.setFillColor(self.color or score_color(int(self.value)))
            c.roundRect(0, 0, w, self.height, r, stroke=0, fill=1)


class StackedBar(Flowable):
    """Segments [(value, color)] laid end to end — severity mix."""

    def __init__(self, segments, width: float, height: float = 3 * mm):
        super().__init__()
        self.segments = [(v, c) for v, c in segments if v > 0]
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        total = sum(v for v, _ in self.segments) or 1
        x = 0
        c.saveState()
        p = c.beginPath()
        p.roundRect(0, 0, self.width, self.height, self.height / 2)
        c.clipPath(p, stroke=0, fill=0)
        if not self.segments:
            c.setFillColor(BORDER)
            c.rect(0, 0, self.width, self.height, stroke=0, fill=1)
        for v, col in self.segments:
            w = self.width * v / total
            c.setFillColor(col)
            c.rect(x, 0, w + 0.3, self.height, stroke=0, fill=1)
            x += w
        c.restoreState()


class IconTile(Flowable):
    """Small rounded square with a simple vector glyph (no icon font needed)."""

    def __init__(self, kind: str, fg, bg, size: float = 8 * mm):
        super().__init__()
        self.kind, self.fg, self.bg, self.size = kind, fg, bg, size
        self.width = self.height = size

    def draw(self):
        c = self.canv
        s = self.size
        c.saveState()
        c.setFillColor(self.bg)
        c.roundRect(0, 0, s, s, s * 0.24, stroke=0, fill=1)
        c.setStrokeColor(self.fg)
        c.setFillColor(self.fg)
        c.setLineWidth(s * 0.07)
        c.setLineCap(1)
        c.setLineJoin(1)
        k = self.kind
        if k == "consent":  # shield with tick
            p = c.beginPath()
            p.moveTo(s * .5, s * .80); p.lineTo(s * .74, s * .71); p.lineTo(s * .74, s * .50)
            p.curveTo(s * .74, s * .33, s * .62, s * .25, s * .5, s * .20)
            p.curveTo(s * .38, s * .25, s * .26, s * .33, s * .26, s * .50)
            p.lineTo(s * .26, s * .71); p.close()
            c.drawPath(p, stroke=1, fill=0)
            p = c.beginPath(); p.moveTo(s * .40, s * .50); p.lineTo(s * .47, s * .43); p.lineTo(s * .60, s * .57)
            c.drawPath(p, stroke=1, fill=0)
        elif k == "analytics":  # rising line chart
            p = c.beginPath(); p.moveTo(s * .25, s * .75); p.lineTo(s * .25, s * .25); p.lineTo(s * .77, s * .25)
            c.drawPath(p, stroke=1, fill=0)
            p = c.beginPath(); p.moveTo(s * .33, s * .38); p.lineTo(s * .46, s * .54); p.lineTo(s * .56, s * .45); p.lineTo(s * .72, s * .66)
            c.drawPath(p, stroke=1, fill=0)
        elif k == "journey":  # route: two dots joined by an S path
            c.circle(s * .30, s * .30, s * .07, stroke=1, fill=0)
            c.circle(s * .70, s * .72, s * .07, stroke=1, fill=0)
            p = c.beginPath(); p.moveTo(s * .37, s * .30); p.lineTo(s * .62, s * .30)
            p.curveTo(s * .76, s * .30, s * .76, s * .51, s * .62, s * .51)
            p.lineTo(s * .38, s * .51)
            p.curveTo(s * .24, s * .51, s * .24, s * .72, s * .38, s * .72)
            p.lineTo(s * .63, s * .72)
            c.drawPath(p, stroke=1, fill=0)
        elif k == "alert":  # triangle with !
            p = c.beginPath(); p.moveTo(s * .5, s * .78); p.lineTo(s * .78, s * .26); p.lineTo(s * .22, s * .26); p.close()
            c.drawPath(p, stroke=1, fill=0)
            c.line(s * .5, s * .58, s * .5, s * .44)
            c.circle(s * .5, s * .34, s * .02, stroke=1, fill=1)
        elif k == "check":
            p = c.beginPath(); p.moveTo(s * .30, s * .50); p.lineTo(s * .44, s * .36); p.lineTo(s * .70, s * .64)
            c.drawPath(p, stroke=1, fill=0)
        elif k == "list":
            for i, y in enumerate((.68, .50, .32)):
                c.circle(s * .30, s * y, s * .025, stroke=1, fill=1)
                c.line(s * .40, s * y, s * .72, s * y)
        else:  # dot
            c.circle(s * .5, s * .5, s * .12, stroke=0, fill=1)
        c.restoreState()


def module_icon(module: str, size: float = 8 * mm) -> IconTile:
    fg, bg = module_color(module)
    return IconTile(module if module in ("consent", "analytics", "journey") else "dot", fg, bg, size)


# --------------------------------------------------------------------------
# Layout helpers
# --------------------------------------------------------------------------
def heading_with_icon(icon: Flowable, title: str, sub: Optional[str] = None, style: str = "H2",
                      width: float = CONTENT_WIDTH) -> Table:
    text = [Paragraph(esc(title), STYLES[style].clone("hwi", spaceBefore=0, spaceAfter=0))]
    if sub:
        text.append(Paragraph(sub, STYLES["Small"]))
    t = Table([[icon, text]], colWidths=[icon.width + 3 * mm, width - icon.width - 3 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def card(rows: List[list], col_widths: Sequence[float], accent=None, background=WHITE,
         padding: float = 4 * mm, border=BORDER) -> Table:
    """A rounded bordered box. With `accent`, a coloured strip runs down the left edge."""
    if accent is not None:
        rows = [[""] + list(r) for r in rows]
        col_widths = [1.4 * mm] + list(col_widths)
    t = Table(rows, colWidths=list(col_widths), cornerRadii=[6, 6, 6, 6])
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("BOX", (0, 0), (-1, -1), 0.6, border),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), padding),
        ("RIGHTPADDING", (0, 0), (-1, -1), padding),
        ("TOPPADDING", (0, 0), (-1, -1), 1.2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
        ("TOPPADDING", (0, 0), (-1, 0), padding * 0.8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), padding * 0.8),
    ]
    if accent is not None:
        style += [
            ("BACKGROUND", (0, 0), (0, -1), accent),
            ("LEFTPADDING", (0, 0), (0, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ]
    t.setStyle(TableStyle(style))
    return t


def stat_tiles(items: Iterable[tuple], width: float = CONTENT_WIDTH, cols: Optional[int] = None) -> Table:
    """items: (value, label[, value_color]) -> a row of equal tiles."""
    items = list(items)
    if not items:
        return Spacer(1, 0)
    cols = cols or len(items)
    gap = 3 * mm
    tile_w = (width - gap * (cols - 1)) / cols
    cells = []
    for it in items:
        value, label = it[0], it[1]
        color = it[2] if len(it) > 2 and it[2] is not None else TEXT_PRIMARY
        inner = Table(
            [[Paragraph(f'<font color="{hexstr(color)}">{esc(value)}</font>', STYLES["Stat"])],
             [Paragraph(esc(label), STYLES["StatLabel"])]],
            colWidths=[tile_w], cornerRadii=[6, 6, 6, 6],
        )
        inner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), WHITE),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 3.5 * mm),
            ("TOPPADDING", (0, 0), (-1, 0), 3 * mm),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 3 * mm),
            ("TOPPADDING", (0, 1), (-1, 1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ]))
        cells.append(inner)
    rows, widths = [], []
    for i in range(0, len(cells), cols):
        chunk = cells[i:i + cols]
        row = []
        for j, cell in enumerate(chunk):
            row.append(cell)
            if j < cols - 1:
                row.append("")
        while len(row) < cols * 2 - 1:
            row.append("")
        rows.append(row)
    for j in range(cols):
        widths.append(tile_w)
        if j < cols - 1:
            widths.append(gap)
    t = Table(rows, colWidths=widths)
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), gap),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def data_table(header: Sequence[str], rows: List[list], widths: Sequence[float],
               align_right: Sequence[int] = (), zebra: bool = False) -> Table:
    """Light table: soft grey header, thin row dividers, no heavy grid.
    Cells may be strings (escaped + wrapped) or flowables."""
    def cell(v, col):
        if isinstance(v, (Flowable, list)):
            return v
        st = STYLES["TDRight"] if col in align_right else STYLES["TD"]
        return Paragraph(soft_wrap("" if v is None else str(v)), st)

    data = [[Paragraph(esc(h), STYLES["TH"].clone("thr", alignment=2) if i in align_right else STYLES["TH"])
             for i, h in enumerate(header)]]
    data += [[cell(v, i) for i, v in enumerate(r)] for r in rows]
    t = Table(data, colWidths=list(widths), repeatRows=1, cornerRadii=[5, 5, 5, 5])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), SURFACE_SUNKEN),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.6 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.6 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.9 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.9 * mm),
    ]
    if zebra:
        style.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SURFACE_SUNKEN]))
    t.setStyle(TableStyle(style))
    return t


def note_box(text: str, fg=TEXT_SECONDARY, bg=SURFACE_SUNKEN, width: float = CONTENT_WIDTH) -> Table:
    t = Table([[Paragraph(text, STYLES["Small"].clone("nb", textColor=fg))]], colWidths=[width], cornerRadii=[5, 5, 5, 5])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6 * mm),
    ]))
    return t


def section_intro(kicker: str, title: str, lead: Optional[str] = None) -> List[Flowable]:
    out = [Paragraph(esc(kicker), STYLES["Kicker"]), Paragraph(esc(title), STYLES["H1"])]
    if lead:
        out.append(Paragraph(lead, STYLES["Lead"]))
    else:
        out.append(Spacer(1, 4))
    return out


def module_banner(module: str, title: str, score: Optional[int], lead: str, width: float = CONTENT_WIDTH) -> Table:
    """Header block that opens a module section: icon, title, one-line
    explanation, and the module score as a big coloured number."""
    fg, bg = module_color(module)
    icon = module_icon(module, 11 * mm)
    text = [
        Paragraph(esc(title), STYLES["H1"].clone("mb_h", spaceAfter=1)),
        Paragraph(lead, STYLES["BodyMuted"].clone("mb_l", spaceAfter=0)),
    ]
    if score is None:
        score_cell = Paragraph("Not scored", STYLES["Small"])
    else:
        score_cell = [
            Paragraph(f'<font color="{hexstr(score_color(score))}">{score}</font>'
                      f'<font size="9" color="{hexstr(TEXT_TERTIARY)}"> / 100</font>',
                      STYLES["Stat"].clone("mb_s", fontSize=24, leading=26, alignment=2)),
        ]
    t = Table([[icon, text, score_cell]], colWidths=[15 * mm, width - 15 * mm - 34 * mm, 34 * mm],
              cornerRadii=[8, 8, 8, 8])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (0, 0), 0),
    ]))
    return t


def keep(*flowables) -> KeepTogether:
    return KeepTogether(list(flowables))


# --------------------------------------------------------------------------
# Images (compressed so the PDF stays small)
# --------------------------------------------------------------------------
def load_image(path: Optional[str], max_w: float, max_h: float, crop_aspect: Optional[float] = None,
               max_px: int = 1100, quality: int = 72) -> Optional[Image]:
    """Loads a screenshot, optionally crops it to the top `crop_aspect`
    (height / width) part, downsizes it and re-encodes it as JPEG.
    Returns None if the file is missing or unreadable."""
    if not path or not Path(path).is_file():
        return None
    try:
        from PIL import Image as PILImage

        with PILImage.open(path) as im:
            im = im.convert("RGB")
            if crop_aspect:
                h_max = int(im.width * crop_aspect)
                if im.height > h_max:
                    im = im.crop((0, 0, im.width, h_max))
            if im.width > max_px:
                im = im.resize((max_px, int(im.height * max_px / im.width)), PILImage.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            w, h = im.size
        buf.seek(0)
        scale = min(max_w / w, max_h / h)
        img = Image(buf, width=w * scale, height=h * scale)
        img.hAlign = "CENTER"
        return img
    except Exception:  # noqa: BLE001 — a bad image must never break the PDF
        return None


def framed_image(img: Optional[Image], caption: Optional[str], width: float, missing_height: float = 40 * mm) -> Table:
    """An image (or a 'not captured' placeholder) in a thin frame with a caption under it."""
    if img is None:
        body = Table([[Paragraph("Screenshot not available", STYLES["Caption"])]], colWidths=[width - 4 * mm],
                     rowHeights=[missing_height])
        body.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SURFACE_SUNKEN),
                                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    else:
        body = img
    rows = [[body]]
    if caption:
        rows.append([Paragraph(caption, STYLES["Caption"])])
    t = Table(rows, colWidths=[width], cornerRadii=[6, 6, 6, 6])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
    ]))
    return t


def image_grid(cells: List[Table], width: float = CONTENT_WIDTH, cols: int = 2, gap: float = 4 * mm) -> Table:
    if not cells:
        return Spacer(1, 0)
    col_w = (width - gap * (cols - 1)) / cols
    rows = []
    for i in range(0, len(cells), cols):
        chunk = cells[i:i + cols]
        row = []
        for j in range(cols):
            row.append(chunk[j] if j < len(chunk) else "")
            if j < cols - 1:
                row.append("")
        rows.append(row)
    widths = []
    for j in range(cols):
        widths.append(col_w)
        if j < cols - 1:
            widths.append(gap)
    t = Table(rows, colWidths=widths)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), gap),
    ]))
    return t


__all__ = [n for n in dir() if not n.startswith("_")]
