"""
pdf/evidence.py

Renders the "Analytics Validation" and "Consent & Cookie Compliance" /
"Consent Evidence" sections required by requirements §7: the per-vendor
Page View / Scroll / Click / Custom-event runtime verdicts
(analytics/runtime.py's AnalyticsRuntimeResult, surfaced on the payload
as `payload.analytics["runtime_result"]`) and the consent banner's
pass/fail checks plus its four captured screenshots
(`payload.consent`, `payload.screenshots`).

Like pdf/screenshots.py, every section here degrades gracefully: no
analytics/consent module run, or runtime not tested, just means that
section (or sub-section) is omitted rather than raising — the PDF should
never break because a particular audit didn't exercise every check.

Nothing here re-derives pass/fail state; it only formats whatever
reports/generator.py already computed onto the payload (§8: one
canonical data model for dashboard/report/PDF/email).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Image, Paragraph, Spacer, Table, TableStyle

from pdf.theme import BORDER, ERROR, STYLES, SUCCESS, SURFACE_SUNKEN, TEXT_TERTIARY, esc
from reports.generator import ReportPayload
from utils.screenshots import screenshot_url_to_path

_STATUS_LABELS = {
    "passed": "PASSED",
    "failed": "FAILED",
    "not_tested": "NOT TESTED",
    "not_applicable": "N/A",
}

_SCREENSHOT_MAX_WIDTH_MM = 78
_SCREENSHOT_MAX_HEIGHT_MM = 90


def build_evidence_flowables(payload: ReportPayload) -> List[Flowable]:
    """Returns the Analytics Validation + Consent & Cookie Compliance / Evidence sections, or [] if neither ran."""
    story: List[Flowable] = []
    story.extend(_build_analytics_section(payload.analytics))
    story.extend(_build_consent_section(payload.consent, payload.screenshots))
    return story


# --------------------------------------------------------------------------
# Analytics Validation (§7 / §3.3)
# --------------------------------------------------------------------------

def _build_analytics_section(analytics: Optional[dict]) -> List[Flowable]:
    if not analytics:
        return []

    runtime_result = analytics.get("runtime_result") or {}
    vendors: Dict[str, dict] = runtime_result.get("vendors") or {}

    if not analytics.get("runtime_tested") or not vendors:
        return [
            Paragraph("Analytics Validation", STYLES["H1"]),
            Paragraph(
                "Runtime validation (Page View / Scroll / Click) was not run for this audit.",
                STYLES["BodyMuted"],
            ),
            Spacer(1, 10),
        ]

    header = ["Vendor", "Page View", "Scroll", "Click", "Custom Event", "Duplicate PV"]
    rows: List[list] = [header]
    status_cells: List[tuple] = []  # (row_index, col_index, status) for coloring

    for row_index, vendor in enumerate(vendors.values(), start=1):
        name = vendor.get("vendor_name") or vendor.get("vendor_key", "")
        cells = [Paragraph(esc(name), STYLES["TableCell"])]
        for col_index, key in enumerate(
            ("page_view_status", "scroll_status", "click_status", "custom_event_status"), start=1
        ):
            status = vendor.get(key, "not_tested")
            cells.append(Paragraph(esc(_STATUS_LABELS.get(status, status.upper())), STYLES["TableCell"]))
            status_cells.append((row_index, col_index, status))

        duplicate = vendor.get("duplicate_page_view", False)
        dup_status = "failed" if duplicate else "passed"
        cells.append(Paragraph(esc("YES" if duplicate else "NO"), STYLES["TableCell"]))
        status_cells.append((row_index, 5, dup_status))

        rows.append(cells)

    table = Table(rows, colWidths=[36 * mm, 26 * mm, 22 * mm, 22 * mm, 28 * mm, 26 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURFACE_SUNKEN]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index, col_index, status in status_cells:
        if status == "passed":
            style.append(("TEXTCOLOR", (col_index, row_index), (col_index, row_index), SUCCESS))
        elif status == "failed":
            style.append(("TEXTCOLOR", (col_index, row_index), (col_index, row_index), ERROR))
        elif status == "not_applicable":
            style.append(("TEXTCOLOR", (col_index, row_index), (col_index, row_index), TEXT_TERTIARY))
    table.setStyle(TableStyle(style))

    return [
        Paragraph("Analytics Validation", STYLES["H1"]),
        Paragraph(
            "Live runtime check of Page View, Scroll, Click, and Custom Event tracking per vendor.",
            STYLES["BodyMuted"],
        ),
        Spacer(1, 4),
        table,
        Spacer(1, 10),
    ]


# --------------------------------------------------------------------------
# Consent & Cookie Compliance + Consent Evidence (§7 / §4)
# --------------------------------------------------------------------------

_CONSENT_CHECKS = (
    ("has_cookie_banner", "Cookie consent banner present"),
    ("banner_blocks_scripts_pre_consent", "Non-essential scripts blocked before consent"),
    ("gdpr_compliant", "GDPR compliant"),
    ("ccpa_compliant", "CCPA compliant"),
    ("privacy_policy_found", "Privacy policy found"),
)

_RUNTIME_CHECKS = (
    ("reject_blocks_tracking", "Reject blocks tracking"),
    ("accept_allows_tracking", "Accept allows tracking"),
    ("personalize_exposes_controls", "Personalize/Manage exposes controls"),
)


def _build_consent_section(consent: Optional[dict], screenshots: List[dict]) -> List[Flowable]:
    if not consent:
        return []

    story: List[Flowable] = [Paragraph("Consent & Cookie Compliance", STYLES["H1"])]

    rows: List[list] = [["Check", "Result"]]
    bool_cells: List[tuple] = []

    for row_index, (field, label) in enumerate(_CONSENT_CHECKS, start=1):
        value = consent.get(field)
        rows.append([Paragraph(esc(label), STYLES["TableCell"]), _bool_cell(value)])
        bool_cells.append((row_index, value))

    if consent.get("runtime_tested"):
        for field, label in _RUNTIME_CHECKS:
            value = consent.get(field)
            row_index = len(rows)
            rows.append([Paragraph(esc(label), STYLES["TableCell"]), _bool_cell(value)])
            bool_cells.append((row_index, value))
    else:
        row_index = len(rows)
        rows.append([
            Paragraph("Reject / Accept / Personalize runtime checks", STYLES["TableCell"]),
            Paragraph(esc("NOT TESTED"), STYLES["TableCellMuted"]),
        ])

    table = Table(rows, colWidths=[110 * mm, 44 * mm], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURFACE_SUNKEN]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index, value in bool_cells:
        if value is True:
            style.append(("TEXTCOLOR", (1, row_index), (1, row_index), SUCCESS))
        elif value is False:
            style.append(("TEXTCOLOR", (1, row_index), (1, row_index), ERROR))
    table.setStyle(TableStyle(style))

    story.extend([table, Spacer(1, 6)])

    trackers = consent.get("third_party_trackers") or []
    cookies = consent.get("cookies_detected") or []
    story.append(Paragraph(
        f"{len(cookies)} cookie(s) detected, {len(trackers)} third-party tracker(s) identified.",
        STYLES["BodyMuted"],
    ))
    if trackers:
        story.append(Paragraph(esc(", ".join(trackers[:12])), STYLES["Caption"]))
    story.append(Spacer(1, 10))

    story.extend(_build_consent_evidence(screenshots))
    return story


def _bool_cell(value: Optional[bool]) -> Paragraph:
    if value is None:
        return Paragraph(esc("N/A"), STYLES["TableCellMuted"])
    return Paragraph(esc("PASS" if value else "FAIL"), STYLES["TableCell"])


def _build_consent_evidence(screenshots: List[dict]) -> List[Flowable]:
    """Embeds the four consent-flow screenshots (initial/preferences/reject/accept) in a 2x2 grid."""
    consent_shots = [s for s in screenshots if s.get("key", "").startswith("consent-")]
    if not consent_shots:
        return []

    story: List[Flowable] = [Paragraph("Consent Evidence", STYLES["H1"])]

    cells = []
    for shot in consent_shots:
        image = _load_evidence_image(shot.get("url"))
        if image is None:
            continue
        caption = Paragraph(esc(shot.get("label", shot.get("key", ""))), STYLES["Caption"])
        cells.append(_evidence_cell_table(image, caption))

    if not cells:
        story.append(Paragraph("Screenshots were not available for this audit.", STYLES["BodyMuted"]))
        story.append(Spacer(1, 10))
        return story

    # Lay out two screenshots per row.
    grid_rows = []
    for i in range(0, len(cells), 2):
        pair = cells[i:i + 2]
        row = pair if len(pair) == 2 else [pair[0], ""]
        grid_rows.append(row)

    grid = Table(grid_rows, colWidths=[85 * mm, 85 * mm])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))

    story.extend([grid, Spacer(1, 10)])
    return story


def _evidence_cell_table(image: Image, caption: Paragraph) -> Table:
    """Wraps one screenshot + caption as a mini single-cell table so it lays out as one grid unit."""
    inner = Table([[image], [caption]], colWidths=[80 * mm])
    inner.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return inner


def _load_evidence_image(shot_url: Optional[str]) -> Optional[Image]:
    if not shot_url:
        return None

    disk_path = screenshot_url_to_path(shot_url)
    if not disk_path:
        return None

    path = Path(disk_path)
    if not path.is_file():
        return None

    try:
        image = Image(str(path))
        max_width = _SCREENSHOT_MAX_WIDTH_MM * mm
        max_height = _SCREENSHOT_MAX_HEIGHT_MM * mm
        scale = min(max_width / image.imageWidth, max_height / image.imageHeight, 1.0)
        image.drawWidth = image.imageWidth * scale
        image.drawHeight = image.imageHeight * scale
        image.hAlign = "CENTER"
        return image
    except Exception:  # noqa: BLE001 — a corrupt/unreadable image should never break the PDF
        return None
