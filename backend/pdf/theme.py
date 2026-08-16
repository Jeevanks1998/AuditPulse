"""
pdf/theme.py

Shared visual constants for the whole pdf/ package — brand colors, fonts,
and a set of reusable ParagraphStyles — so cover.py, summary.py,
charts.py, screenshots.py, recommendations.py, and appendix.py all draw
from one palette instead of redefining hex codes independently (the same
problem reports/html_report.py solves for the HTML export with its one
`_CSS` block).

Colors are copied from assets/css/variables.css's design tokens (kept in
sync by hand, since this package has no CSS to read from — reportlab
draws its own glyphs/shapes, it doesn't run a browser). `Sora`/`Inter`
(the frontend's --font-display/--font-body) aren't available to reportlab
without embedding TTFs, so Helvetica/Helvetica-Bold stand in for both
everywhere in this package; `--font-mono` maps to Courier for the same
reason.
"""

from __future__ import annotations

from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

# Bumped whenever the section order, page templates, or any structural
# layout piece in this package changes — reports/report_storage.py folds
# this into the on-disk PDF cache key so a layout change invalidates old
# cached PDFs instead of quietly continuing to serve them (§11 "Cache" /
# the PDF validation checklist's "not accidentally served from an
# outdated cache").
PDF_LAYOUT_VERSION = 2

# --------------------------------------------------------------------------
# Brand palette (assets/css/variables.css)
# --------------------------------------------------------------------------
PRIMARY = colors.HexColor("#2563EB")
PRIMARY_SOFT = colors.HexColor("#DBEAFE")
SUCCESS = colors.HexColor("#10B981")
SUCCESS_SOFT = colors.HexColor("#D1FAE5")
WARNING = colors.HexColor("#F59E0B")
WARNING_SOFT = colors.HexColor("#FEF3C7")
ERROR = colors.HexColor("#EF4444")
ERROR_SOFT = colors.HexColor("#FEE2E2")

TEXT_PRIMARY = colors.HexColor("#0F172A")
TEXT_SECONDARY = colors.HexColor("#64748B")
TEXT_TERTIARY = colors.HexColor("#94A3B8")
BORDER = colors.HexColor("#E2E8F0")
SURFACE_SUNKEN = colors.HexColor("#F8FAFC")
WHITE = colors.white

SEVERITY_COLORS = {"critical": ERROR, "warning": WARNING, "info": PRIMARY}
SEVERITY_SOFT_COLORS = {"critical": ERROR_SOFT, "warning": WARNING_SOFT, "info": PRIMARY_SOFT}

# Same good/mid/low banding as config.constants.SCORE_BANDS on the frontend.
SCORE_BAND_GOOD = 80
SCORE_BAND_MID = 50


def score_color(score: int) -> colors.Color:
    """Bands a 0-100 score into the same good/mid/low colors as the frontend's score chips."""
    if score >= SCORE_BAND_GOOD:
        return SUCCESS
    if score >= SCORE_BAND_MID:
        return WARNING
    return ERROR


def severity_color(severity: str) -> colors.Color:
    return SEVERITY_COLORS.get(severity, PRIMARY)


def severity_soft_color(severity: str) -> colors.Color:
    return SEVERITY_SOFT_COLORS.get(severity, PRIMARY_SOFT)


# Shared PASS/FAIL/NOT TESTED/N/A vocabulary (§3.10/§3.9's four explicit
# states) — the one place every section that renders a runtime/consent
# status label reads its wording from, so pdf/evidence.py and any other
# module never drift into different phrasing for the same state.
STATUS_LABELS = {
    "passed": "PASS",
    "failed": "FAIL",
    "not_tested": "NOT TESTED",
    "not_applicable": "N/A",
}
STATUS_COLORS = {"passed": SUCCESS, "failed": ERROR, "not_tested": TEXT_TERTIARY, "not_applicable": TEXT_TERTIARY}

# good/mid/bad -> the same wording assets/js/dashboard.js's healthBadgeLabel
# already shows on the dashboard, so the PDF's "Overall Status" never
# invents a label the rest of the app doesn't use (§3.3).
SCORE_BAND_LABELS = {"good": "Healthy", "mid": "Needs Attention", "bad": "Issues Found"}


def score_band(score: int) -> str:
    """Same tier boundaries as `score_color` above, returned as a key ("good"/"mid"/"bad")
    instead of a color — for callers (e.g. cover.py's status line) that need the label, not the ring."""
    if score >= SCORE_BAND_GOOD:
        return "good"
    if score >= SCORE_BAND_MID:
        return "mid"
    return "bad"


def esc(text) -> str:
    """XML-escapes audit/AI-derived text before it goes into a Paragraph.

    Every Paragraph body in this package is built from findings/summaries
    that can originate from an AI provider or a crawled page (the same
    trust boundary reports/html_report.py's `html.escape` calls out) —
    reportlab's Paragraph parses a small XML-like markup, so unescaped
    text could otherwise be misread as tags.
    """
    return _xml_escape(str(text if text is not None else ""))


FONT_BODY = "Helvetica"
FONT_BODY_BOLD = "Helvetica-Bold"
FONT_DISPLAY = "Helvetica-Bold"
FONT_MONO = "Courier"

PAGE_MARGIN_MM = 18

_stylesheet = getSampleStyleSheet()


def _style(name: str, parent: str = "Normal", **kwargs) -> ParagraphStyle:
    return ParagraphStyle(name, parent=_stylesheet[parent], **kwargs)


STYLES = {
    "CoverTitle": _style(
        "CoverTitle", fontName=FONT_DISPLAY, fontSize=26, leading=32,
        textColor=TEXT_PRIMARY, alignment=TA_CENTER, spaceAfter=6,
    ),
    "CoverSubtitle": _style(
        "CoverSubtitle", fontName=FONT_BODY, fontSize=12, leading=16,
        textColor=TEXT_SECONDARY, alignment=TA_CENTER, spaceAfter=4,
    ),
    "CoverMeta": _style(
        "CoverMeta", fontName=FONT_MONO, fontSize=9, leading=13,
        textColor=TEXT_TERTIARY, alignment=TA_CENTER, spaceAfter=2,
    ),
    "H1": _style(
        "H1", fontName=FONT_DISPLAY, fontSize=15, leading=19,
        textColor=TEXT_PRIMARY, spaceBefore=2, spaceAfter=10,
    ),
    "H2": _style(
        "H2", fontName=FONT_BODY_BOLD, fontSize=11, leading=14,
        textColor=TEXT_PRIMARY, spaceBefore=12, spaceAfter=6,
    ),
    "Body": _style(
        "Body", fontName=FONT_BODY, fontSize=9.5, leading=14,
        textColor=TEXT_PRIMARY, alignment=TA_LEFT, spaceAfter=6,
    ),
    "BodyMuted": _style(
        "BodyMuted", fontName=FONT_BODY, fontSize=8.5, leading=12,
        textColor=TEXT_SECONDARY, spaceAfter=4,
    ),
    "Caption": _style(
        "Caption", fontName=FONT_BODY, fontSize=8, leading=11,
        textColor=TEXT_TERTIARY, alignment=TA_CENTER, spaceBefore=4,
    ),
    "TableCell": _style(
        "TableCell", fontName=FONT_BODY, fontSize=8.5, leading=12,
        textColor=TEXT_PRIMARY,
    ),
    "TableCellMuted": _style(
        "TableCellMuted", fontName=FONT_BODY, fontSize=8, leading=11,
        textColor=TEXT_SECONDARY,
    ),
    "TableHeader": _style(
        "TableHeader", fontName=FONT_BODY_BOLD, fontSize=8.5, leading=11,
        textColor=WHITE,
    ),
    "Badge": _style(
        "Badge", fontName=FONT_BODY_BOLD, fontSize=6.5, leading=8,
        textColor=WHITE, alignment=TA_CENTER,
    ),
    "ListItem": _style(
        "ListItem", fontName=FONT_BODY, fontSize=9, leading=13,
        textColor=TEXT_PRIMARY, spaceAfter=5, leftIndent=2,
    ),
    "ListItemMeta": _style(
        "ListItemMeta", fontName=FONT_BODY, fontSize=7.5, leading=10,
        textColor=TEXT_SECONDARY,
    ),
    "FooterText": _style(
        "FooterText", fontName=FONT_BODY, fontSize=7.5, leading=10,
        textColor=TEXT_TERTIARY,
    ),
    # Executive Summary metric cards (§3.3: Overall Score / Critical
    # Findings / Total Findings / Weakest Module).
    "MetricValue": _style(
        "MetricValue", fontName=FONT_DISPLAY, fontSize=20, leading=24,
        textColor=TEXT_PRIMARY, alignment=TA_CENTER, spaceAfter=1,
    ),
    "MetricLabel": _style(
        "MetricLabel", fontName=FONT_BODY_BOLD, fontSize=7.5, leading=10,
        textColor=TEXT_SECONDARY, alignment=TA_CENTER,
    ),
    # Small uppercase-ish label above a section's H1 (e.g. cover scope
    # line, a page's section eyebrow) — never actual uppercase transform
    # since reportlab Paragraphs don't do CSS text-transform, so callers
    # pass already-uppercased text.
    "Eyebrow": _style(
        "Eyebrow", fontName=FONT_BODY_BOLD, fontSize=8, leading=11,
        textColor=TEXT_SECONDARY, alignment=TA_CENTER, spaceAfter=8,
    ),
    # Generated section index / Table of Contents entries.
    "TOCEntry": _style(
        "TOCEntry", fontName=FONT_BODY, fontSize=10, leading=18,
        textColor=TEXT_PRIMARY, leftIndent=4,
    ),
    "TOCNumber": _style(
        "TOCNumber", fontName=FONT_BODY_BOLD, fontSize=10, leading=18,
        textColor=PRIMARY,
    ),
}
