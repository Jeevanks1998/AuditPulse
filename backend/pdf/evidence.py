"""
pdf/evidence.py

Renders the "Analytics Technology Detection", "Analytics Validation"
and "Consent & Cookie Compliance" / "Consent Evidence" sections
required by requirements §3.9/§3.10: the static per-vendor detection
picture (analytics.analytics_score's `vendor_configs`/`trackers_detected`,
surfaced on the payload as `payload.analytics["vendor_configs"]` /
`["trackers_detected"]`), the per-vendor Page View / Scroll / Click /
Custom-event *runtime* verdicts (analytics/runtime.py's
AnalyticsRuntimeResult, surfaced as `payload.analytics["runtime_result"]`),
and the consent banner's pass/fail checks plus its four captured
screenshots (`payload.consent`, `payload.screenshots`).

Phase 3 (Analytics and Consent Evidence): static detection and runtime
validation are rendered as two distinct tables/sections rather than one
— §3.9 explicitly calls this out ("Separate static detection from
runtime validation"), and folding them together previously meant that
whenever `runtime_tested` was false the section showed *nothing at
all* about what was actually detected in markup, even though that
static data (vendor_configs / trackers_detected) is always available
independent of whether the runtime pass ran.

Like pdf/screenshots.py, every section here degrades gracefully: no
analytics/consent module run, or runtime not tested, just means that
part of the section is omitted (or shown as "not tested"/"none
detected") rather than raising — the PDF should never break because a
particular audit didn't exercise every check.

Nothing here re-derives pass/fail state or which vendors were detected;
it only formats whatever reports/generator.py already computed onto
the payload (§8: one canonical data model for dashboard/report/PDF/
email), so no vendor can ever appear here that the real detectors
didn't actually find (§9 "No Dummy Data Rule").
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Flowable, Image, Paragraph, Spacer, Table, TableStyle

from analytics.analytics_score import TRACKER_DISPLAY_NAMES
from pdf.theme import BORDER, ERROR, STATUS_COLORS, STATUS_LABELS, STYLES, SUCCESS, SURFACE_SUNKEN, TEXT_TERTIARY, esc
from reports.generator import ReportPayload
from utils.screenshots import screenshot_url_to_path

_SCREENSHOT_MAX_WIDTH_MM = 78
_SCREENSHOT_MAX_HEIGHT_MM = 90


def build_evidence_flowables(payload: ReportPayload) -> List[Flowable]:
    """Returns the Analytics Technology Detection + Analytics Validation +
    Consent & Cookie Compliance / Evidence sections, or [] if neither
    analytics nor consent ran for this audit."""
    story: List[Flowable] = []
    story.extend(_build_analytics_technology_section(payload.analytics))
    story.extend(_build_analytics_section(payload.analytics))
    story.extend(_build_consent_section(payload.consent, payload.screenshots))
    story.extend(_build_journey_section(getattr(payload, "journey_view", None)))
    return story


# --------------------------------------------------------------------------
# Analytics Technology Detection — static (§3.9)
# --------------------------------------------------------------------------

def _build_analytics_technology_section(analytics: Optional[dict]) -> List[Flowable]:
    """
    Renders only the vendors `analytics.analytics_score.build_analytics_summary`
    actually found in the page's markup (`vendor_configs` / `trackers_detected`)
    — never a fixed vendor list (§3.9: "Never show GA4, GTM, Adobe, Piano, Tag
    Commander, etc. unless the backend actually detected them"). Deliberately
    independent of `runtime_tested`/`runtime_result`: this is the *static*
    detection picture, so it renders (or explicitly says nothing was found)
    even when the runtime pass never ran — see _build_analytics_section below
    for the separate, runtime-gated table.
    """
    if not analytics:
        return []

    vendor_configs: Dict[str, List[str]] = analytics.get("vendor_configs") or {}

    story: List[Flowable] = [
        Paragraph("Analytics Technology Detection", STYLES["H1"]),
        Paragraph(
            "Tracking technologies identified in the page's markup, independent of whether "
            "runtime behaviour was validated.",
            STYLES["BodyMuted"],
        ),
        Spacer(1, 4),
    ]

    if not vendor_configs:
        story.append(Paragraph("No analytics or tag-management technology was detected on this page.", STYLES["BodyMuted"]))
        story.append(Spacer(1, 10))
        return story

    rows: List[list] = [["Technology", "Detected ID(s)"]]
    for vendor_key, ids in vendor_configs.items():
        label = TRACKER_DISPLAY_NAMES.get(vendor_key, vendor_key)
        id_text = ", ".join(str(i) for i in ids) if ids else "Detected — no configuration ID extracted"
        rows.append([Paragraph(esc(label), STYLES["TableCell"]), Paragraph(esc(id_text), STYLES["TableCell"])])

    table = Table(rows, colWidths=[70 * mm, 90 * mm], repeatRows=1)
    table.setStyle(TableStyle([
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
    ]))

    story.extend([table, Spacer(1, 10)])
    return story


# --------------------------------------------------------------------------
# Analytics Validation — runtime (§7 / §3.3 / §3.9)
# --------------------------------------------------------------------------

def _build_analytics_section(analytics: Optional[dict]) -> List[Flowable]:
    if not analytics:
        return []

    runtime_result = analytics.get("runtime_result") or {}
    vendors: Dict[str, dict] = runtime_result.get("vendors") or {}

    if not analytics.get("runtime_tested") or not vendors:
        if not analytics.get("runtime_available"):
            explanation = "Runtime validation was not available in the environment this audit ran in."
        elif not (analytics.get("vendor_configs") or {}):
            explanation = "No analytics vendors were detected, so there was nothing to validate at runtime."
        else:
            explanation = "Runtime validation (Page View / Scroll / Click) was not run for this audit."
        return [
            Paragraph("Analytics Runtime Validation", STYLES["H1"]),
            Paragraph(
                explanation + " Shown as NOT TESTED rather than pass/fail.",
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
            cells.append(Paragraph(esc(STATUS_LABELS.get(status, status.upper())), STYLES["TableCell"]))
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
        color = STATUS_COLORS.get(status)
        if color is not None:
            style.append(("TEXTCOLOR", (col_index, row_index), (col_index, row_index), color))
    table.setStyle(TableStyle(style))

    return [
        Paragraph("Analytics Runtime Validation", STYLES["H1"]),
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
)

# Mirrors consent.consent_score.GDPR_CHECK_ORDER / GDPR_CHECK_LABELS — read
# from the `gdpr_checks` dict (not top-level fields like _CONSENT_CHECKS
# above), since these ten replace the old single gdpr_compliant boolean.
_GDPR_CHECKS = (
    ("consent_banner", "Consent banner"),
    ("accept_control", "Accept control"),
    ("reject_control", "Reject control"),
    ("reject_parity", "Reject parity"),
    ("trackers_blocked_pre_consent", "Non-essential trackers blocked before consent"),
    ("cookies_blocked_pre_consent", "Non-essential cookies blocked before consent"),
    ("consent_is_granular", "Consent is granular"),
    ("privacy_policy_available", "Privacy policy available"),
    ("consent_withdrawal_available", "Consent withdrawal available"),
    ("reject_blocks_tracking", "Reject actually blocks tracking"),
)

# Mirrors consent.consent_score.CCPA_CHECK_ORDER / CCPA_CHECK_LABELS — read
# from the `ccpa_checks` dict, same relationship _GDPR_CHECKS above has to
# gdpr_checks. These six replace the old single
# `ccpa_link_found and privacy_policy_url is not None` boolean.
_CCPA_CHECKS = (
    ("privacy_policy_available", "Privacy policy available"),
    ("privacy_choices_link", '"Your Privacy Choices" link present'),
    ("do_not_sell_link", '"Do Not Sell or Share My Information" link present'),
    ("opt_out_mechanism", "Opt-out mechanism reachable"),
    ("gpc_honored", "Global Privacy Control (GPC) signal handling detected"),
    ("opt_out_behavior_verified", "Opt-out actually stops tracking"),
)

_RUNTIME_CHECKS = (
    # reject_blocks_tracking is intentionally omitted here — it's already
    # shown in the GDPR breakdown table above (same underlying
    # ConsentRuntimeResult.reject_blocks_tracking value); repeating it in
    # both tables would just be the same verdict twice.
    ("accept_allows_tracking", "Accept allows tracking"),
    ("personalize_exposes_controls", "Personalize/Manage exposes controls"),
)


def _build_bool_table(rows_spec, values: dict, col_widths=(110 * mm, 44 * mm)) -> Table:
    """Shared helper for the consent/GDPR/runtime check tables below —
    same header row, striping, and PASS/FAIL/N/A coloring for all three."""
    rows: List[list] = [["Check", "Result"]]
    bool_cells: List[tuple] = []
    for row_index, (field, label) in enumerate(rows_spec, start=1):
        value = values.get(field)
        rows.append([Paragraph(esc(label), STYLES["TableCell"]), _bool_cell(value)])
        bool_cells.append((row_index, value))

    table = Table(rows, colWidths=list(col_widths), repeatRows=1)
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
    return table


_STATE_TEXT = {"pass": "PASS", "fail": "FAIL", "not_tested": "NOT TESTED", "info": "INFO", "neutral": "—",
               "not_assessed": "NOT ASSESSED"}


def _grid_table(rows: List[list], col_widths, state_col: Optional[int] = None,
                states: Optional[List[str]] = None) -> Table:
    """Header row + striped body; optional colored PASS/FAIL/NOT TESTED column."""
    cells: List[list] = [[Paragraph(f'<font color="#FFFFFF"><b>{esc(str(h))}</b></font>', STYLES["TableCell"])
                          for h in rows[0]]]
    for r_i, row in enumerate(rows[1:]):
        out = []
        for c_i, value in enumerate(row):
            if state_col is not None and states and c_i == state_col:
                st = states[r_i]
                text = esc(_STATE_TEXT.get(st, st))
                if st in ("pass", "fail"):
                    color = (SUCCESS if st == "pass" else ERROR).hexval()[2:]
                    out.append(Paragraph(f'<font color="#{color}"><b>{text}</b></font>', STYLES["TableCell"]))
                else:
                    out.append(Paragraph(text, STYLES["TableCellMuted"]))
            else:
                out.append(Paragraph(esc(str(value)), STYLES["TableCell"]))
        cells.append(out)
    table = Table(cells, colWidths=list(col_widths), repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SURFACE_SUNKEN]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _build_consent_section(consent: Optional[dict], screenshots: List[dict]) -> List[Flowable]:
    """
    Consent & Cookie Compliance, rendered from the same presentation model
    (reports.consent_view) the report page and dashboard use: headline
    verdicts, regional applicability, framework assessments (or "Not
    assessed"), banner controls, classified pre-consent network and cookie
    evidence, the fresh-scan pipeline, and the four evidence screenshots.
    """
    if not consent:
        return []
    from reports.consent_view import build_consent_view  # local: pdf/* is imported by reports.*

    view = consent.get("report_view") or build_consent_view(consent)
    status = view["status"]
    # Keep the heading with its first table (no orphaned heading at a page foot).
    story: List[Flowable] = [CondPageBreak(70 * mm), Paragraph("Consent & Cookie Compliance", STYLES["H1"])]

    # --- headline verdicts ---------------------------------------------------
    rows = [["Check", "Result", "Status", "Detail"]]
    states = []
    for t in view["tiles"]:
        rows.append([t["label"], t["value"], "", t.get("sub") or ""])
        states.append(t["state"])
    story.append(_grid_table(rows, (40 * mm, 34 * mm, 18 * mm, 62 * mm), state_col=2, states=states))
    story.append(Spacer(1, 8))

    # --- regional applicability ------------------------------------------------
    story.append(Paragraph("Regional Applicability", STYLES["H2"]))
    conf = status.get("confidence")
    story.append(Paragraph(esc(
        f"Region: {status.get('region_label')}" + (f" · Confidence: {conf}" if conf else "")
        + f" · Framework: {status.get('framework_label')} · Regional compliance: {status.get('regional_compliance_label')}"
    ), STYLES["Body"]))
    for ev in (status.get("evidence") or [])[:8]:
        story.append(Paragraph(esc("• " + ev), STYLES["BodyMuted"]))
    if status.get("note"):
        story.append(Paragraph(esc(status["note"]), STYLES["BodyMuted"]))

    # --- frameworks ------------------------------------------------------------
    for fw in view["frameworks"]:
        if not fw["applicable"]:
            story.append(Paragraph(esc(f"{fw['label']}: {fw.get('reason') or 'Not assessed'}"),
                                   STYLES["BodyMuted"]))
            continue
        story.append(Paragraph(esc(f"{fw['label']} Assessment — {fw['status_label']}"), STYLES["H2"]))
        rows = [["Check", "Result"]] + [[c["label"], ""] for c in fw.get("checks", [])]
        story.append(_grid_table(rows, (114 * mm, 40 * mm), state_col=1,
                                 states=[c["state"] for c in fw.get("checks", [])]))
        for f in fw.get("failed", [])[:10]:
            story.append(Paragraph(esc(f"FAILED {f['label']}: {f.get('reason') or ''}"), STYLES["BodyMuted"]))
            for item in (f.get("items") or [])[:5]:
                story.append(Paragraph(esc("    – " + str(item)), STYLES["BodyMuted"]))
        story.append(Spacer(1, 6))

    # --- banner controls ---------------------------------------------------------
    story.append(Paragraph("Banner Controls", STYLES["H2"]))
    if view["controls"]:
        rows = [["Displayed text", "Detected action", "Evidence"]]
        for c in view["controls"][:20]:
            rows.append([c["label"], c["action"] + (" (2nd layer)" if c.get("layer") == 2 else ""), c["evidence"]])
        story.append(_grid_table(rows, (58 * mm, 44 * mm, 52 * mm)))
    else:
        story.append(Paragraph("No controls were found inside a consent banner.", STYLES["BodyMuted"]))

    # --- network ------------------------------------------------------------------
    before = (view.get("network") or {}).get("before_consent") or []
    if before:
        story.append(Paragraph("Network Before Consent (classified)", STYLES["H2"]))
        rows = [["Category", "Requests", "Classification", "Vendors"]]
        for r in before:
            rows.append([r["label"], str(r["count"]), r["note"], ", ".join(r["vendors"][:4])])
        story.append(_grid_table(rows, (34 * mm, 18 * mm, 60 * mm, 42 * mm)))

    # --- cookies --------------------------------------------------------------------
    if view.get("cookies"):
        story.append(Paragraph("Cookies Before Consent", STYLES["H2"]))
        rows = [["Group", "Count", "Cookies"]]
        for g in view["cookies"]:
            rows.append([g["label"], str(g["count"]), "; ".join(g["items"][:6])])
        story.append(_grid_table(rows, (48 * mm, 16 * mm, 90 * mm)))

    # --- legacy fields still shown --------------------------------------------------
    trackers = consent.get("third_party_trackers") or []
    cookies = consent.get("cookies_detected") or []
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"{len(cookies)} cookie(s) set in the initial HTTP response, {len(trackers)} third-party tracking cookie domain(s).",
        STYLES["BodyMuted"],
    ))

    # --- scan pipeline --------------------------------------------------------------
    if view.get("pipeline"):
        story.append(Paragraph("Scan Pipeline (fresh scan)", STYLES["H2"]))
        story.append(Paragraph(esc(
            f"Scan {status.get('scan_id')} · {status.get('fresh_browser_contexts') or 0} fresh browser context(s)"
            + (f" · started {str(status.get('scanned_at'))[:19].replace('T', ' ')} UTC" if status.get("scanned_at") else "")
        ), STYLES["BodyMuted"]))
        rows = [["#", "Step", "Status", "Detail"]]
        for p in view["pipeline"]:
            rows.append([str(p.get("step")), p.get("name", ""), p.get("status", ""), p.get("detail", "")])
        story.append(_grid_table(rows, (8 * mm, 50 * mm, 20 * mm, 76 * mm)))

    story.append(Spacer(1, 10))
    story.extend(_build_consent_evidence(screenshots))
    return story


def _bool_cell(value: Optional[bool]) -> Paragraph:
    if value is None:
        return Paragraph(esc("N/A"), STYLES["TableCellMuted"])
    return Paragraph(esc("PASS" if value else "FAIL"), STYLES["TableCell"])


def _build_consent_evidence(screenshots: List[dict]) -> List[Flowable]:
    """Embeds the consent-flow screenshots in a 2x2 grid.

    The Initial Banner slot always renders — with an "Evidence not
    captured" placeholder if it's missing — since §3.11 expects it under
    Consent Evidence regardless; Preferences/Reject/Accept are optional and
    are only shown when actually captured (§3.11/§10).
    """
    consent_shots = {s.get("key"): s for s in screenshots if s.get("key", "").startswith("consent-")}

    story: List[Flowable] = [Paragraph("Consent Evidence", STYLES["H1"])]

    cells = []
    initial = consent_shots.get("consent-initial")
    image = _load_evidence_image(initial.get("url")) if initial else None
    label = initial.get("label", "Initial Banner") if initial else "Initial Banner"
    caption = Paragraph(esc(label), STYLES["Caption"])
    cells.append(_evidence_cell_table(image if image is not None else _evidence_not_captured(), caption))

    for key, shot in consent_shots.items():
        if key == "consent-initial":
            continue
        image = _load_evidence_image(shot.get("url"))
        if image is None:
            continue
        caption = Paragraph(esc(shot.get("label", key)), STYLES["Caption"])
        cells.append(_evidence_cell_table(image, caption))

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


def _evidence_not_captured() -> Table:
    """Neutral placeholder standing in for a missing consent screenshot (§10)."""
    cell = Paragraph("Evidence not captured", STYLES["BodyMuted"])
    box = Table([[cell]], colWidths=[_SCREENSHOT_MAX_WIDTH_MM * mm], rowHeights=[40 * mm])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE_SUNKEN),
        ("BOX", (0, 0), (-1, -1), 0.75, BORDER),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_TERTIARY),
    ]))
    return box


def _evidence_cell_table(image, caption: Paragraph) -> Table:
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


# --------------------------------------------------------------------------
# Customer Journey (journey/ — reports.journey_view)
# --------------------------------------------------------------------------

def _journey_image(url: Optional[str], max_w_mm: float = 80, max_h_mm: float = 55) -> Optional[Image]:
    from reports.journey_view import screenshot_file

    disk = screenshot_file(url)
    if not disk:
        return None
    try:
        img = Image(disk)
        scale = min(max_w_mm * mm / img.imageWidth, max_h_mm * mm / img.imageHeight, 1.0)
        img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
        img.hAlign = "CENTER"
        return img
    except Exception:  # noqa: BLE001
        return None


def _build_journey_section(view: Optional[dict]) -> List[Flowable]:
    """CUSTOMER JOURNEY: health, interaction summary, journey map, tracking
    coverage, gaps, forms, downloads, CTAs, evidence screenshots, recommendations."""
    if not view:
        return []
    story: List[Flowable] = [CondPageBreak(70 * mm), Paragraph("Customer Journey", STYLES["H1"])]
    if not view.get("available"):
        story.append(Paragraph(esc("The customer journey scan could not run: " + (view.get("error") or "unknown error")),
                               STYLES["BodyMuted"]))
        return story

    score = view.get("score")
    story.append(Paragraph("Journey Health", STYLES["H2"]))
    story.append(Paragraph(esc(
        f"Technical journey health: {score if score is not None else 'not scored'}"
        + (" / 100" if score is not None else "")
        + f" · consent: {view.get('consent_state') or 'n/a'}"), STYLES["Body"]))
    rows = [["Measure", "Value"]] + [[t["label"], str(t["value"])] for t in view.get("tiles") or []]
    story.append(_grid_table(rows, (100 * mm, 54 * mm)))

    if view.get("by_type"):
        story.append(Paragraph("Interaction Summary", STYLES["H2"]))
        rows = [["Interaction type", "Discovered"]] + [[b["type"], str(b["count"])] for b in view["by_type"]]
        story.append(_grid_table(rows, (100 * mm, 54 * mm)))

    nodes = (view.get("map") or {}).get("nodes") or {}
    journeys = (view.get("map") or {}).get("journeys") or []
    if journeys:
        story.append(Paragraph("Journey Map", STYLES["H2"]))
        for j in journeys[:15]:
            parts = []
            for sid in j.get("steps") or []:
                n = nodes.get(sid) or {}
                if n.get("kind") == "page":
                    parts.append(n.get("path") or "/")
                else:
                    if n.get("test_status") == "failed":
                        mark = "(FAILED)"
                    elif n.get("test_status") == "skipped":
                        mark = "(not executed - safety)"
                    else:
                        mark = {"tracked": "(tracked)", "duplicate": "(duplicate event)",
                                "not_tracked": "(NOT TRACKED)"}.get(n.get("tracking_status"), "(not tested)")
                    parts.append(f"[{n.get('type_label')}] {n.get('label')} {mark}")
            story.append(Paragraph(esc(f"{j.get('name')}: " + " > ".join(parts)), STYLES["BodyMuted"]))

    cov = (view.get("tracking") or {}).get("coverage_by_type") or []
    if cov:
        story.append(Paragraph("Tracking Coverage", STYLES["H2"]))
        rows = [["Type", "Tested", "Tracked", "Not tracked", "Duplicate"]] + [
            [c["type"], str(c["tested"]), str(c["tracked"]), str(c["not_tracked"]), str(c["duplicate"])] for c in cov]
        story.append(_grid_table(rows, (54 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm)))

    gaps = view.get("gaps") or []
    story.append(Paragraph("Tracking Gaps", STYLES["H2"]))
    if gaps:
        rows = [["Interaction", "Type", "Page", "Observed"]] + [
            [g["label"], g["type_label"], g["page_path"], g.get("tracking_note") or "No event"] for g in gaps[:20]]
        story.append(_grid_table(rows, (48 * mm, 24 * mm, 30 * mm, 52 * mm)))
    else:
        story.append(Paragraph("No tracking gaps among the tested conversion interactions.", STYLES["BodyMuted"]))

    forms = [f for f in view.get("forms") or [] if not f.get("is_search")]
    if forms:
        story.append(Paragraph("Forms", STYLES["H2"]))
        rows = [["Form", "Page", "Fields (required)", "Submit", "Validation"]] + [[
            f.get("heading") or f.get("name") or "Form", (f.get("page_url") or "")[-40:],
            f"{f.get('visible_fields')} ({f.get('required_fields')})", ", ".join(f.get("submit_controls") or []) or "—",
            f.get("validation") or ""] for f in forms[:15]]
        story.append(_grid_table(rows, (32 * mm, 34 * mm, 24 * mm, 26 * mm, 38 * mm)))
        story.append(Paragraph("Forms are never submitted on production sites; submission tracking is reported as not verifiable.",
                               STYLES["BodyMuted"]))

    downloads = view.get("downloads") or []
    if downloads:
        story.append(Paragraph("Downloads", STYLES["H2"]))
        rows = [["Download", "Type", "HTTP", "Tracking"]] + [[
            d.get("label") or "", (d.get("file_type") or "").upper(), str(d.get("http_status") or "—"),
            {"tracked": "Tracked", "duplicate": "Duplicate", "not_tracked": "Not detected"}.get(d.get("tracking"), "Not tested")]
            for d in downloads[:20]]
        story.append(_grid_table(rows, (70 * mm, 20 * mm, 20 * mm, 44 * mm)))

    ctas = view.get("ctas") or []
    if ctas:
        story.append(Paragraph("CTAs", STYLES["H2"]))
        rows = [["CTA", "Page", "Test", "Tracking"]] + [
            [c["label"], c["page_path"], c["test_label"], c["tracking_label"]] for c in ctas[:20]]
        story.append(_grid_table(rows, (54 * mm, 34 * mm, 34 * mm, 32 * mm)))

    evidence = [r for r in view.get("evidence") or [] if (r.get("screenshots") or {}).get("highlighted")]
    if evidence:
        story.append(CondPageBreak(80 * mm))
        story.append(Paragraph("Evidence Screenshots", STYLES["H2"]))
        cells, row = [], []
        for r in evidence[:8]:
            img = _journey_image(r["screenshots"]["highlighted"])
            if img is None:
                continue
            cap = Paragraph(esc(f"#{r['index']} {r['type_label']}: {r['label']} — {r['tracking_label']}"), STYLES["Caption"])
            row.append([img, cap])
            if len(row) == 2:
                cells.append(row)
                row = []
        if row:
            cells.append(row + [""] * (2 - len(row)))
        if cells:
            t = Table(cells, colWidths=[85 * mm, 85 * mm])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
            story.append(t)

    recs = view.get("recommendations") or []
    if recs:
        story.append(Paragraph("Recommendations", STYLES["H2"]))
        for r in recs[:12]:
            story.append(Paragraph(esc(f"[{(r.get('severity') or '').upper()}] {r.get('title')} — {r.get('recommendation')}"),
                                   STYLES["BodyMuted"]))
    return story
