"""
pdf/theme.py

Shared visual constants for the pdf/ package: the AuditPulse UI palette
(assets/css/theme.css), the Source Sans 3 type family (embedded from
pdf/assets/fonts, SIL Open Font License — see OFL.txt there), and the
ParagraphStyles every section uses.

If the font files can't be registered for any reason the package falls
back to Helvetica, so a font problem never breaks report generation.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle

# Bumped whenever the layout changes — reports/report_storage.py folds it
# into the PDF cache key so old cached PDFs are never served after a
# redesign.
# v6: full redesign — cover with module scores, "Start here" top fixes,
# per-module sections with consent + journey screenshots, compact
# appendix, compressed images.
# v7: no separate "Issues to fix" section; more journey screenshots.
PDF_LAYOUT_VERSION = 7

# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------
_FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"


def _register_fonts() -> tuple:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        pdfmetrics.registerFont(TTFont("SourceSans3", str(_FONT_DIR / "SourceSans3-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("SourceSans3-SemiBold", str(_FONT_DIR / "SourceSans3-SemiBold.ttf")))
        pdfmetrics.registerFont(TTFont("SourceSans3-Bold", str(_FONT_DIR / "SourceSans3-Bold.ttf")))
        pdfmetrics.registerFontFamily(
            "SourceSans3", normal="SourceSans3", bold="SourceSans3-Bold",
            italic="SourceSans3", boldItalic="SourceSans3-Bold",
        )
        return "SourceSans3", "SourceSans3-SemiBold", "SourceSans3-Bold"
    except Exception:  # noqa: BLE001 — never let a font problem break the PDF
        return "Helvetica", "Helvetica-Bold", "Helvetica-Bold"


FONT_BODY, FONT_SEMIBOLD, FONT_BOLD = _register_fonts()
FONT_DISPLAY = FONT_BOLD
FONT_BODY_BOLD = FONT_BOLD
FONT_MONO = "Courier"

# --------------------------------------------------------------------------
# Palette (assets/css/theme.css)
# --------------------------------------------------------------------------
INK = colors.HexColor("#101828")
PRIMARY = colors.HexColor("#4F46E5")
PRIMARY_DARK = colors.HexColor("#3730A3")
PRIMARY_SOFT = colors.HexColor("#EEF2FF")

SUCCESS = colors.HexColor("#12B76A")
SUCCESS_SOFT = colors.HexColor("#ECFDF3")
SUCCESS_TEXT = colors.HexColor("#027A48")
WARNING = colors.HexColor("#F79009")
WARNING_SOFT = colors.HexColor("#FFFAEB")
WARNING_TEXT = colors.HexColor("#B54708")
ERROR = colors.HexColor("#F04438")
ERROR_SOFT = colors.HexColor("#FEF3F2")
ERROR_TEXT = colors.HexColor("#B42318")
INFO = colors.HexColor("#2E90FA")
INFO_SOFT = colors.HexColor("#EFF8FF")
INFO_TEXT = colors.HexColor("#175CD3")

TEXT_PRIMARY = INK
TEXT_SECONDARY = colors.HexColor("#475467")
TEXT_TERTIARY = colors.HexColor("#667085")
BORDER = colors.HexColor("#EAECF0")
BORDER_STRONG = colors.HexColor("#D0D5DD")
SURFACE_SUNKEN = colors.HexColor("#F9FAFB")
CANVAS = colors.HexColor("#F6F7FB")
WHITE = colors.white

# One colour per audit module — same as the web app's --mod-* tokens.
MODULE_COLORS = {
    "consent": (colors.HexColor("#7C3AED"), colors.HexColor("#F4EBFF")),
    "analytics": (colors.HexColor("#2563EB"), colors.HexColor("#EAF2FF")),
    "journey": (colors.HexColor("#0D9488"), colors.HexColor("#E6F6F4")),
}
MODULE_LABELS = {"consent": "Consent", "analytics": "Analytics", "journey": "Customer Journey"}


def module_color(module: str):
    return MODULE_COLORS.get(module, (PRIMARY, PRIMARY_SOFT))


# Severity: colour + plain-language meaning used everywhere in the report.
SEVERITY_META = {
    "critical": {"label": "Critical", "action": "Fix now", "fg": ERROR, "bg": ERROR_SOFT, "text": ERROR_TEXT},
    "warning": {"label": "Warning", "action": "Fix soon", "fg": WARNING, "bg": WARNING_SOFT, "text": WARNING_TEXT},
    "info": {"label": "Info", "action": "Good to know", "fg": INFO, "bg": INFO_SOFT, "text": INFO_TEXT},
}
SEVERITY_COLORS = {k: v["fg"] for k, v in SEVERITY_META.items()}
SEVERITY_SOFT_COLORS = {k: v["bg"] for k, v in SEVERITY_META.items()}

SCORE_BAND_GOOD = 80
SCORE_BAND_MID = 50
SCORE_BAND_LABELS = {"good": "Healthy", "mid": "Needs attention", "bad": "Issues found"}


def score_band(score: int) -> str:
    if score >= SCORE_BAND_GOOD:
        return "good"
    if score >= SCORE_BAND_MID:
        return "mid"
    return "bad"


def score_color(score: int) -> colors.Color:
    return {"good": SUCCESS, "mid": WARNING, "bad": ERROR}[score_band(score)]


def score_soft_color(score: int) -> colors.Color:
    return {"good": SUCCESS_SOFT, "mid": WARNING_SOFT, "bad": ERROR_SOFT}[score_band(score)]


def score_text_color(score: int) -> colors.Color:
    return {"good": SUCCESS_TEXT, "mid": WARNING_TEXT, "bad": ERROR_TEXT}[score_band(score)]


def severity_color(severity: str) -> colors.Color:
    return SEVERITY_COLORS.get(severity, INFO)


def severity_soft_color(severity: str) -> colors.Color:
    return SEVERITY_SOFT_COLORS.get(severity, INFO_SOFT)


# PASS / FAIL / NOT TESTED vocabulary for runtime + consent checks.
STATE_META = {
    "pass": ("Pass", SUCCESS_TEXT, SUCCESS_SOFT),
    "passed": ("Pass", SUCCESS_TEXT, SUCCESS_SOFT),
    "fail": ("Fail", ERROR_TEXT, ERROR_SOFT),
    "failed": ("Fail", ERROR_TEXT, ERROR_SOFT),
    "not_tested": ("Not tested", TEXT_TERTIARY, SURFACE_SUNKEN),
    "not_applicable": ("N/A", TEXT_TERTIARY, SURFACE_SUNKEN),
    "not_assessed": ("Not assessed", TEXT_TERTIARY, SURFACE_SUNKEN),
    "info": ("Info", INFO_TEXT, INFO_SOFT),
    "neutral": ("—", TEXT_TERTIARY, SURFACE_SUNKEN),
}
STATUS_LABELS = {"passed": "PASS", "failed": "FAIL", "not_tested": "NOT TESTED", "not_applicable": "N/A"}


def hexstr(color) -> str:
    return "#" + color.hexval()[2:]


def esc(text) -> str:
    """XML-escape crawled / AI text before it goes into a Paragraph."""
    return _xml_escape(str(text if text is not None else ""))


PAGE_MARGIN_MM = 16


def _style(name: str, **kwargs) -> ParagraphStyle:
    base = dict(fontName=FONT_BODY, fontSize=9.5, leading=13.5, textColor=TEXT_PRIMARY)
    base.update(kwargs)
    return ParagraphStyle(name, **base)


STYLES = {
    # cover
    "CoverEyebrow": _style("CoverEyebrow", fontName=FONT_SEMIBOLD, fontSize=10, leading=13, textColor=colors.HexColor("#C7D2FE")),
    "CoverTitle": _style("CoverTitle", fontName=FONT_BOLD, fontSize=30, leading=34, textColor=WHITE),
    "CoverSite": _style("CoverSite", fontName=FONT_SEMIBOLD, fontSize=14, leading=18, textColor=colors.HexColor("#E0E7FF")),
    "CoverMeta": _style("CoverMeta", fontSize=9, leading=12, textColor=colors.HexColor("#C7D2FE")),
    # headings
    "Kicker": _style("Kicker", fontName=FONT_SEMIBOLD, fontSize=9, leading=12, textColor=PRIMARY, spaceAfter=2),
    "H1": _style("H1", fontName=FONT_BOLD, fontSize=19, leading=23, spaceAfter=4),
    "H2": _style("H2", fontName=FONT_BOLD, fontSize=12.5, leading=16, spaceBefore=10, spaceAfter=5),
    "H3": _style("H3", fontName=FONT_BOLD, fontSize=10.5, leading=14, spaceAfter=2),
    "Lead": _style("Lead", fontSize=10.5, leading=15.5, textColor=TEXT_SECONDARY, spaceAfter=8),
    "Body": _style("Body", spaceAfter=4),
    "BodyMuted": _style("BodyMuted", fontSize=9, leading=12.5, textColor=TEXT_SECONDARY, spaceAfter=3),
    "Small": _style("Small", fontSize=8.5, leading=11.5, textColor=TEXT_SECONDARY),
    "SmallBold": _style("SmallBold", fontName=FONT_SEMIBOLD, fontSize=8.5, leading=11.5, textColor=TEXT_PRIMARY),
    "Caption": _style("Caption", fontSize=8, leading=10.5, textColor=TEXT_TERTIARY, alignment=TA_CENTER, spaceBefore=3),
    "Label": _style("Label", fontName=FONT_SEMIBOLD, fontSize=8, leading=10, textColor=TEXT_TERTIARY),
    # tables
    "TH": _style("TH", fontName=FONT_SEMIBOLD, fontSize=8.5, leading=11, textColor=TEXT_TERTIARY),
    "TD": _style("TD", fontSize=9, leading=12),
    "TDBold": _style("TDBold", fontName=FONT_SEMIBOLD, fontSize=9, leading=12),
    "TDMuted": _style("TDMuted", fontSize=8.5, leading=11.5, textColor=TEXT_SECONDARY),
    "TDRight": _style("TDRight", fontSize=9, leading=12, alignment=TA_RIGHT),
    # numbers
    "Stat": _style("Stat", fontName=FONT_BOLD, fontSize=20, leading=23),
    "StatLabel": _style("StatLabel", fontName=FONT_SEMIBOLD, fontSize=8.5, leading=11, textColor=TEXT_SECONDARY),
    "Pill": _style("Pill", fontName=FONT_SEMIBOLD, fontSize=7.5, leading=9, alignment=TA_CENTER),
    "Center": _style("Center", alignment=TA_CENTER),
    "Left": _style("Left", alignment=TA_LEFT),
}

# Back-compat aliases used by older call sites.
STYLES["TableCell"] = STYLES["TD"]
STYLES["TableCellMuted"] = STYLES["TDMuted"]
