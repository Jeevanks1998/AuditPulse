"""
pdf/modules.py

One section per audited module — Consent, Analytics, Customer Journey.
Each opens with a coloured banner (icon, plain-language "what this
checks", module score), then shows the evidence as short, light tables
with Pass / Fail labels instead of raw dumps. Long lists are capped here;
the appendix carries the full detail.
"""

from __future__ import annotations

from typing import List, Optional

from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Flowable, KeepTogether, PageBreak, Paragraph, Spacer, Table, TableStyle

from pdf.components import (
    CONTENT_WIDTH,
    Bar,
    card,
    data_table,
    framed_image,
    image_grid,
    load_image,
    module_banner,
    note_box,
    pill,
    short_url,
    soft_wrap,
    state_pill,
)
from pdf.theme import (
    BORDER,
    ERROR_SOFT,
    ERROR_TEXT,
    FONT_SEMIBOLD,
    INFO_SOFT,
    INFO_TEXT,
    STATE_META,
    STYLES,
    SUCCESS_SOFT,
    SUCCESS_TEXT,
    SURFACE_SUNKEN,
    TEXT_SECONDARY,
    TEXT_TERTIARY,
    WARNING_SOFT,
    WARNING_TEXT,
    WHITE,
    esc,
    hexstr,
    module_color,
)
from reports.generator import ReportPayload
from utils.screenshots import screenshot_url_to_path as _basename_lookup

W = CONTENT_WIDTH
MAX_ROWS = 12


def screenshot_url_to_path(url: Optional[str]) -> Optional[str]:
    """A "/screenshots/..." URL -> the file on disk. Journey shots live in
    sub-folders (/screenshots/journey/<scan>/<page>/x.png), so try the full
    relative path first, then the flat basename layout consent uses."""
    if not url:
        return None
    from pathlib import Path

    from config.settings import settings

    root = Path(getattr(settings, "SCREENSHOT_DIR", "screenshots"))
    rel = url.split("/screenshots/", 1)[1] if "/screenshots/" in url else url.lstrip("/")
    candidate = root / rel
    try:
        if ".." not in Path(rel).parts and candidate.is_file():
            return str(candidate)
    except (OSError, ValueError):
        pass
    return _basename_lookup(url)


def _score(payload: ReportPayload, module: str) -> Optional[int]:
    for c in payload.score_grid:
        if c.module == module:
            return int(c.score)
    return None


def _h2(text: str, sub: Optional[str] = None) -> List[Flowable]:
    out = [CondPageBreak(40 * mm), Paragraph(esc(text), STYLES["H2"])]
    if sub:
        out.append(Paragraph(sub, STYLES["BodyMuted"]))
    return out


def _more_note(shown: int, total: int, what: str) -> List[Flowable]:
    if total > shown:
        return [Paragraph(f"Showing {shown} of {total} {what}. The full list is in the appendix.",
                          STYLES["Small"].clone("more", textColor=TEXT_TERTIARY, spaceBefore=1.5 * mm))]
    return []


def _check_tiles(tiles: List[dict], cols: int = 3) -> Table:
    """Status tiles: label, value and a Pass/Fail pill."""
    gap = 3 * mm
    tw = (W - gap * (cols - 1)) / cols
    cells = []
    for t in tiles:
        state = (t.get("state") or "neutral").lower()
        label, fg, bg = STATE_META.get(state, STATE_META["neutral"])
        body = Table(
            [[Paragraph(esc(t.get("label", "")), STYLES["Label"]), pill(label, fg, bg, width=19 * mm)],
             [Paragraph(esc(str(t.get("value", "—"))), STYLES["H3"].clone("ct_v", spaceAfter=0)), ""],
             [Paragraph(esc(t.get("sub") or ""), STYLES["Small"].clone("ct_s", textColor=TEXT_TERTIARY)), ""]],
            colWidths=[tw - 21 * mm, 21 * mm], cornerRadii=[6, 6, 6, 6],
        )
        body.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), WHITE),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("SPAN", (0, 1), (1, 1)), ("SPAN", (0, 2), (1, 2)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3.5 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("TOPPADDING", (0, 0), (-1, 0), 3 * mm), ("TOPPADDING", (0, 1), (-1, -1), 0.6 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, -1), (-1, -1), 3 * mm),
        ]))
        cells.append(body)
    rows, widths = [], []
    for i in range(0, len(cells), cols):
        chunk = cells[i:i + cols]
        row = []
        for j in range(cols):
            row.append(chunk[j] if j < len(chunk) else "")
            if j < cols - 1:
                row.append("")
        rows.append(row)
    for j in range(cols):
        widths.append(tw)
        if j < cols - 1:
            widths.append(gap)
    grid = Table(rows, colWidths=widths)
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), gap),
    ]))
    return grid


def _shot(url: Optional[str], caption: str, width: float, crop: Optional[float] = 0.62):
    path = screenshot_url_to_path(url) if url else None
    img = load_image(path, width - 4 * mm, 62 * mm, crop_aspect=crop)
    return framed_image(img, caption, width, missing_height=34 * mm)  # caption: already-escaped markup


# --------------------------------------------------------------------------
# Consent
# --------------------------------------------------------------------------
_NET_VERDICT = {
    "tracking": ("Tracking", ERROR_TEXT, ERROR_SOFT),
    "infrastructure": ("Not tracking", SUCCESS_TEXT, SUCCESS_SOFT),
    "unknown": ("Unclear", WARNING_TEXT, WARNING_SOFT),
}


def build_consent_section(payload: ReportPayload) -> List[Flowable]:
    cv = payload.consent_view or {}
    if not cv and not payload.consent:
        return []
    story: List[Flowable] = [module_banner(
        "consent", "Consent & cookies", _score(payload, "consent"),
        "Does the cookie banner work, and does the site wait for the visitor's choice before tracking them?")]
    story.append(Spacer(1, 5 * mm))

    tiles = cv.get("tiles") or []
    if tiles:
        story.append(_check_tiles(tiles))

    status = cv.get("status") or {}
    if status.get("note"):
        story.append(note_box(esc(status["note"])))
        story.append(Spacer(1, 2 * mm))

    fw = cv.get("frameworks") or []
    if fw:
        story += _h2("Privacy laws", "Which rules apply depends on where the site's visitors are. "
                                     "Results are only given once the region is established.")
        rows = []
        for f in fw:
            st = (f.get("status") or "not_assessed").lower()
            state = {"compliant": "pass", "pass": "pass", "passed": "pass", "non_compliant": "fail",
                     "fail": "fail", "failed": "fail", "not_applicable": "not_applicable"}.get(st, "not_assessed")
            failed = f.get("failed") or []
            detail = f.get("reason") or ""
            if failed:
                detail = (detail + " Failed: " + ", ".join(str(x) for x in failed)).strip()
            rows.append([Paragraph(esc(f.get("label", "")), STYLES["TDBold"]),
                         "Yes" if f.get("applicable") else "Not established",
                         state_pill(state, 24 * mm), detail])
        story.append(data_table(["Law", "Applies", "Result", "Notes"], rows, [36 * mm, 26 * mm, 30 * mm, W - 92 * mm]))

    net = (cv.get("network") or {}).get("before_consent") or []
    if net:
        story += _h2("What loaded before the visitor chose",
                     "Every request the page made before anyone clicked the banner, grouped by type. "
                     "Only “Tracking” rows are a problem before consent.")
        rows = []
        for n in sorted(net, key=lambda x: (x.get("kind") != "tracking", -(x.get("count") or 0)))[:MAX_ROWS]:
            label, fg, bg = _NET_VERDICT.get(n.get("kind") or "unknown", _NET_VERDICT["unknown"])
            vendors = ", ".join(n.get("vendors") or []) or "—"
            rows.append([Paragraph(esc(n.get("label") or n.get("category", "")), STYLES["TDBold"]),
                         str(n.get("count", 0)), pill(label, fg, bg, width=24 * mm), vendors])
        story.append(data_table(["Type", "Requests", "Verdict", "Who"], rows,
                                [40 * mm, 20 * mm, 30 * mm, W - 90 * mm], align_right=(1,)))

    cookies = cv.get("cookies") or []
    if cookies:
        story += _h2("Cookies set before consent")
        rows = []
        for g in cookies:
            items = []
            for it in (g.get("items") or [])[:8]:
                if isinstance(it, dict):
                    nm = it.get("name") or ""
                    dom = it.get("domain") or ""
                    items.append(f"{nm} ({dom})" if dom else nm)
                else:
                    items.append(str(it))
            more = (g.get("count") or 0) - len(items)
            text = ", ".join(items) + (f" + {more} more" if more > 0 else "")
            rows.append([Paragraph(esc(g.get("label", "")), STYLES["TDBold"]), str(g.get("count", 0)), text])
        story.append(data_table(["Group", "Count", "Cookies"], rows, [44 * mm, 16 * mm, W - 60 * mm], align_right=(1,)))

    controls = cv.get("controls") or []
    if controls:
        story += _h2("Banner buttons we found")
        rows = []
        for c in controls[:MAX_ROWS]:
            layer = c.get("layer")
            where = "Banner" if layer in (1, None) else "Preferences panel"
            rows.append([Paragraph(esc(c.get("label", "")), STYLES["TDBold"]), c.get("action_label") or "—", where])
        story.append(data_table(["Button text", "What it does", "Where"], rows, [70 * mm, 54 * mm, W - 124 * mm]))
        story += _more_note(min(len(controls), MAX_ROWS), len(controls), "buttons")

    shots = [s for s in (cv.get("screenshots") or []) if s.get("url")]
    if shots:
        cw = (W - 4 * mm) / 2
        if any(screenshot_url_to_path(s["url"]) for s in shots[:4]):
            cells = [_shot(s["url"], f'<b>{esc(s.get("label", ""))}</b>', cw, crop=0.62) for s in shots[:4]]
            story.append(KeepTogether(_h2("Screenshots", "The banner and the page after each choice, captured in a fresh browser.")
                                      + [image_grid(cells[:2], W, cols=2)]))
            if cells[2:]:
                story.append(image_grid(cells[2:], W, cols=2))
        else:
            story += _h2("Screenshots")
            story.append(note_box("The screenshots for this audit are no longer stored on the server, so they can't be "
                                  "shown here. Run the audit again to capture fresh ones."))
    return story


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------
_CATEGORY_LABELS = {"ANALYTICS": "Analytics", "ADVERTISING": "Advertising", "TAG_MANAGER": "Tag manager",
                    "SOCIAL": "Social", "CMP": "Consent tool"}
_PHASE_LABELS = {"load": "page load", "scroll": "scroll", "click": "click"}


def _status_state(v: Optional[str]) -> str:
    v = (v or "not_tested").lower()
    return {"passed": "pass", "failed": "fail", "not_tested": "not_tested", "not_applicable": "not_applicable"}.get(v, v)


def build_analytics_section(payload: ReportPayload) -> List[Flowable]:
    an = payload.analytics
    if not an:
        return []
    story: List[Flowable] = [module_banner(
        "analytics", "Analytics & tracking", _score(payload, "analytics"),
        "Which tracking tools run on the site, and do they record page views, scrolls and clicks correctly?")]
    story.append(Spacer(1, 5 * mm))

    rr = an.get("runtime_result") or {}
    cov = an.get("site_coverage") or {}
    tiles = []
    tms = [t.get("vendor") for t in (rr.get("observed_tags") or []) if t.get("category") == "TAG_MANAGER" and t.get("vendor")]
    if an.get("gtm_container_id"):
        tms.insert(0, f"Google Tag Manager ({an['gtm_container_id']})")
    elif an.get("tag_manager_detected"):
        tms.insert(0, "Google Tag Manager")
    tms = list(dict.fromkeys(tms))
    tiles.append({"label": "Tag manager", "value": ", ".join(tms[:2]) if tms else "Not found",
                  "sub": "Loads the other tracking tags", "state": "pass" if tms else "neutral"})
    if cov.get("pages_scanned"):
        with_a = cov.get("pages_with_analytics", 0)
        total = cov.get("pages_scanned", 0)
        tiles.append({"label": "Pages with analytics", "value": f"{with_a} of {total}",
                      "sub": "Pages where a tracking tag was found",
                      "state": "pass" if with_a == total else "fail" if with_a == 0 else "info"})
    tiles.append({"label": "Live browser check",
                  "value": "Ran" if an.get("runtime_tested") else "Not run",
                  "sub": (f"Consent: {rr.get('consent_state')}" if rr.get("consent_state") else
                          (rr.get("error") or "")[:60]),
                  "state": "pass" if an.get("runtime_tested") else "not_tested"})
    story.append(_check_tiles(tiles))

    vendors = (rr.get("vendors") or {}) if isinstance(rr, dict) else {}
    if vendors:
        story += _h2("Live browser check",
                     "We opened the page in a real browser, accepted cookies, scrolled and clicked, "
                     "and watched what each tool sent.")
        rows = []
        for v in vendors.values():
            dup = v.get("duplicate_page_view")
            rows.append([
                Paragraph(esc(v.get("vendor_name") or v.get("vendor_key", "")), STYLES["TDBold"]),
                state_pill(_status_state(v.get("page_view_status")), 21 * mm),
                state_pill(_status_state(v.get("scroll_status")), 21 * mm),
                state_pill(_status_state(v.get("click_status")), 21 * mm),
                state_pill(_status_state(v.get("custom_event_status")), 21 * mm),
                pill("Yes", ERROR_TEXT, ERROR_SOFT, width=12 * mm) if dup else
                pill("No", SUCCESS_TEXT, SUCCESS_SOFT, width=12 * mm) if dup is False else "—",
            ])
        story.append(data_table(["Tool", "Page view", "Scroll", "Click", "Custom event", "Double count"], rows,
                                [W - 5 * 25 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm]))
        story.append(Paragraph("N/A = that kind of event isn't set up for this tool, which is normal for tag managers.",
                               STYLES["Small"].clone("na", textColor=TEXT_TERTIARY, spaceBefore=1.5 * mm)))

    tags = rr.get("observed_tags") or []
    if tags:
        story += _h2("Every tool seen in the browser",
                     "All analytics, advertising and tag-manager traffic captured during the live check — "
                     "found by watching the network, not from a fixed list.")
        rows = []
        for t in sorted(tags, key=lambda x: -(x.get("requests") or 0))[:MAX_ROWS + 3]:
            phases = ", ".join(_PHASE_LABELS.get(p, p) for p in t.get("phases") or []) or "—"
            rows.append([Paragraph(esc(t.get("vendor", "")), STYLES["TDBold"]),
                         _CATEGORY_LABELS.get(t.get("category"), (t.get("category") or "").title()),
                         phases, f'{t.get("collection_requests", 0)} / {t.get("requests", 0)}'])
        story.append(data_table(["Tool", "Type", "Sent data on", "Data hits / requests"], rows,
                                [W - 108 * mm, 32 * mm, 42 * mm, 34 * mm], align_right=(3,)))

    pages = an.get("page_results") or []
    if len(pages) > 1:
        story += _h2("Page by page", "What was found on each scanned page.")
        rows = []
        for p in pages[:MAX_ROWS]:
            trackers = ", ".join(p.get("trackers_detected") or []) or "None found"
            n_find = len(p.get("findings") or [])
            rows.append([soft_wrap(short_url(p.get("url"), limit=70)), trackers,
                         str(n_find) if n_find else "—"])
        story.append(data_table(["Page", "Tools found", "Issues"], rows, [W - 92 * mm, 74 * mm, 18 * mm], align_right=(2,)))
        story += _more_note(min(len(pages), MAX_ROWS), len(pages), "pages")
    return story


# --------------------------------------------------------------------------
# Customer Journey
# --------------------------------------------------------------------------
def _rate_rows(rates: dict) -> List[Flowable]:
    items = [("Interactions that worked", rates.get("success_rate")),
             ("Key actions that were tracked", rates.get("conversion_tracking_coverage")),
             ("Tests with screenshot evidence", rates.get("evidence_rate"))]
    rows = []
    for label, val in items:
        if val is None:
            continue
        pct = round(float(val) * 100)
        rows.append([Paragraph(esc(label), STYLES["TD"]), Bar(pct, 90 * mm, 2.4 * mm),
                     Paragraph(f"<b>{pct}%</b>", STYLES["TDRight"])])
    if not rows:
        return []
    t = Table(rows, colWidths=[W - 112 * mm, 94 * mm, 18 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
                           ("LINEBELOW", (0, 0), (-1, -2), 0.5, BORDER)]))
    return [t]


def build_journey_section(payload: ReportPayload) -> List[Flowable]:
    jv = payload.journey_view or {}
    if not jv:
        return []
    story: List[Flowable] = [module_banner(
        "journey", "Customer journey", _score(payload, "journey"),
        "We clicked through the site like a visitor — buttons, links, forms and downloads — and checked "
        "that each one works and is measured.")]
    story.append(Spacer(1, 5 * mm))
    if not jv.get("available"):
        story.append(note_box(esc(jv.get("error") or "The journey scan did not complete for this audit.")))
        return story

    c = jv.get("counts") or {}
    gaps_n = c.get("tracking_gaps", 0)
    tiles = [
        {"label": "Pages visited", "value": c.get("pages_scanned", 0), "sub": f"{c.get('interactions_discovered', 0)} clickable elements found", "state": "info"},
        {"label": "Tested", "value": f"{c.get('successful_interactions', 0)} of {c.get('interactions_tested', 0)} worked",
         "sub": "Clicked in a real browser",
         "state": "pass" if c.get("interactions_tested") and c.get("successful_interactions") == c.get("interactions_tested") else "info"},
        {"label": "Tracking gaps", "value": gaps_n, "sub": f"{c.get('tracked_interactions', 0)} actions were tracked",
         "state": "fail" if gaps_n else "pass"},
    ]
    story.append(_check_tiles(tiles))
    story += _rate_rows(jv.get("rates") or {})

    cov = (jv.get("tracking") or {}).get("coverage_by_type") or []
    if cov:
        story += _h2("Tracking by type of action", "For each kind of action we tested: how many were measured by analytics.")
        rows = []
        for r in cov:
            tested = r.get("tested") or 0
            tracked = r.get("tracked") or 0
            pct = round(100 * tracked / tested) if tested else 0
            rows.append([Paragraph(esc(r.get("type", "")), STYLES["TDBold"]), str(tested), str(tracked),
                         str(r.get("not_tracked") or 0), Bar(pct, 34 * mm, 2.2 * mm,
                                                            color=module_color("journey")[0])])
        story.append(data_table(["Action", "Tested", "Tracked", "Not tracked", "Coverage"], rows,
                                [W - 118 * mm, 20 * mm, 20 * mm, 26 * mm, 52 * mm], align_right=(1, 2, 3)))

    broken = [i for i in jv.get("interactions") or [] if i.get("test_status") == "failed"]
    if broken:
        story += _h2("Didn't work", "Clicked, but nothing useful happened.")
        rows = [[Paragraph(soft_wrap(i.get("label") or "—"), STYLES["TDBold"]), i.get("type_label") or "",
                 soft_wrap(i.get("page_path") or short_url(i.get("page"))), soft_wrap(i.get("observed") or "")]
                for i in broken[:MAX_ROWS]]
        story.append(data_table(["Element", "Type", "Page", "What happened"], rows,
                                [44 * mm, 22 * mm, 34 * mm, W - 100 * mm]))
        story += _more_note(min(len(broken), MAX_ROWS), len(broken), "items")

    gaps = jv.get("gaps") or []
    if gaps:
        story += _h2("Worked, but not tracked", "These actions work for visitors, but analytics never hears about them.")
        rows = [[Paragraph(soft_wrap(g.get("label") or "—"), STYLES["TDBold"]), g.get("type_label") or "",
                 soft_wrap(g.get("page_path") or short_url(g.get("page"))),
                 soft_wrap(short_url(g.get("destination")) if g.get("destination") else "—")]
                for g in gaps[:MAX_ROWS]]
        story.append(data_table(["Element", "Type", "Page", "Goes to"], rows,
                                [56 * mm, 22 * mm, 40 * mm, W - 118 * mm]))
        story += _more_note(min(len(gaps), MAX_ROWS), len(gaps), "gaps")

    forms = [f for f in jv.get("forms") or [] if not f.get("is_search")]
    if forms:
        story += _h2("Forms")
        rows = []
        for f in forms[:MAX_ROWS]:
            name = f.get("heading") or f.get("name") or "Form"
            fields = f"{f.get('visible_fields', 0)} fields, {f.get('required_fields', 0)} required"
            tracking = ", ".join(f.get("tracking_hints") or []) or "No tracking hint"
            rows.append([Paragraph(esc(name), STYLES["TDBold"]), soft_wrap(short_url(f.get("page_url"))), fields, tracking])
        story.append(data_table(["Form", "Page", "Fields", "Tracking"], rows, [44 * mm, 40 * mm, 42 * mm, W - 126 * mm]))
        story.append(Paragraph("Forms are never submitted during the audit, so no real data is sent.",
                               STYLES["Small"].clone("fn", textColor=TEXT_TERTIARY, spaceBefore=1.5 * mm)))

    dls = jv.get("downloads") or []
    if dls:
        story += _h2("Downloads")
        rows = []
        for d in dls[:MAX_ROWS]:
            tr = (d.get("tracking") or "not_tested").lower()
            tstate = {"tracked": ("Tracked", SUCCESS_TEXT, SUCCESS_SOFT), "not_tracked": ("Not tracked", ERROR_TEXT, ERROR_SOFT),
                      "duplicate": ("Counted twice", WARNING_TEXT, WARNING_SOFT)}.get(tr, ("Not tested", TEXT_TERTIARY, SURFACE_SUNKEN))
            http = d.get("http_status")
            rows.append([soft_wrap(short_url(d.get("destination")) or d.get("label") or ""),
                         (d.get("file_type") or "").upper(),
                         pill(str(http) if http else "—", SUCCESS_TEXT if http and http < 400 else ERROR_TEXT,
                              SUCCESS_SOFT if http and http < 400 else ERROR_SOFT, width=12 * mm) if http else "—",
                         pill(tstate[0], tstate[1], tstate[2], width=24 * mm)])
        story.append(data_table(["File", "Type", "Opens", "Tracking"], rows, [W - 70 * mm, 16 * mm, 22 * mm, 32 * mm]))
        story += _more_note(min(len(dls), MAX_ROWS), len(dls), "downloads")

    story += _journey_screenshots(jv, broken, gaps)

    limits = jv.get("limits") or {}
    if limits.get("scan_stopped_by_time_budget") or limits.get("tests_stopped_by_time_budget"):
        story.append(note_box("The scan reached its time limit, so some pages or interactions were not tested.",
                              fg=INFO_TEXT, bg=INFO_SOFT))
    return story


_JOURNEY_STATUS = {
    "failed": ("Didn't work", ERROR_TEXT),
    "not_tracked": ("Worked · not tracked", WARNING_TEXT),
    "duplicate": ("Worked · counted twice", WARNING_TEXT),
    "tracked": ("Worked · tracked", SUCCESS_TEXT),
}
MAX_PAGE_SHOTS = 6
MAX_INTERACTION_SHOTS = 8


def _grid_with_heading(heading: List[Flowable], cells: List[Table]) -> List[Flowable]:
    """Heading kept on the same page as the first row of screenshots."""
    out: List[Flowable] = [KeepTogether(heading + [image_grid(cells[:2], W, cols=2)])]
    for i in range(2, len(cells), 2):
        out.append(image_grid(cells[i:i + 2], W, cols=2))
    return out


def _journey_screenshots(jv: dict, broken: List[dict], gaps: List[dict]) -> List[Flowable]:
    """Screenshots for the Customer Journey section:

    * the pages the scan visited (top of each page), and
    * the tested buttons / links / forms / downloads with the element
      outlined — problems first (didn't work, not tracked), then ones
      that worked and were tracked.

    Only screenshots that are still on disk are shown; if none are, one
    note explains why instead of a wall of empty boxes."""
    cw = (W - 4 * mm) / 2
    story: List[Flowable] = []

    page_cells = []
    for p in jv.get("pages") or []:
        url = p.get("screenshot")
        if url and screenshot_url_to_path(url):
            title = p.get("title") or ""
            path = p.get("path") or short_url(p.get("url"))
            if path == "/":
                path = "Homepage"
            page_cells.append(_shot(url, f"<b>{esc(path)}</b>" + (f" — {esc(title)}" if title else ""), cw, crop=0.62))
        if len(page_cells) >= MAX_PAGE_SHOTS:
            break

    seen, ordered = set(), []
    tested = [i for i in jv.get("interactions") or [] if i.get("test_status") in ("success", "failed")]
    tracked = [i for i in tested if i.get("tracking_status") == "tracked"]
    for it in list(broken) + list(gaps) + [i for i in tested if i.get("tracking_status") == "duplicate"] + tracked:
        key = it.get("index")
        if key in seen:
            continue
        seen.add(key)
        ordered.append(it)

    inter_cells = []
    for it in ordered:
        shots = it.get("screenshots") or {}
        url = shots.get("highlighted") or shots.get("after") or shots.get("before")
        if not (url and screenshot_url_to_path(url)):
            continue
        status_key = "failed" if it.get("test_status") == "failed" else (it.get("tracking_status") or "")
        label, color = _JOURNEY_STATUS.get(status_key, ("Tested", TEXT_SECONDARY))
        page = it.get("page_path") or short_url(it.get("page"))
        if page == "/":
            page = "Homepage"
        caption = (f'<b>{esc(it.get("label") or "Element")}</b> · {esc(it.get("type_label") or "")} on {esc(page)}<br/>'
                   f'<font color="{hexstr(color)}"><b>{esc(label)}</b></font>')
        inter_cells.append(_shot(url, caption, cw, crop=0.62))
        if len(inter_cells) >= MAX_INTERACTION_SHOTS:
            break

    if page_cells:
        story += _grid_with_heading(_h2("Pages visited", "The top of each page the scan opened."), page_cells)
    if inter_cells:
        story += _grid_with_heading(
            _h2("What we clicked", "Each tested element is outlined in red. Problems are shown first."), inter_cells)
    if not page_cells and not inter_cells and (jv.get("pages") or jv.get("evidence")):
        story += _h2("Screenshots")
        story.append(note_box("The screenshots for this audit are no longer stored on the server, so they can't be "
                              "shown here. Run the audit again to capture fresh ones."))
    return story

