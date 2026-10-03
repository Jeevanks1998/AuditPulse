"""
pdf/appendix.py

The reference part at the back: for every issue, the complete list of
places it was found (the issue cards show only the first few), then the
pages that were scanned and the technical scan details. Small type, no
repetition of the explanations already given on "Start here".
"""

from __future__ import annotations

from typing import List

from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Flowable, KeepTogether, PageBreak, Paragraph, Spacer, Table, TableStyle

from pdf.components import CONTENT_WIDTH, data_table, section_intro, short_url, soft_wrap
from pdf.issues import Issue
from pdf.theme import BORDER, MODULE_LABELS, SEVERITY_META, STYLES, TEXT_TERTIARY, esc, hexstr
from reports.generator import ReportPayload

W = CONTENT_WIDTH


def _two_col_list(items: List[str]) -> Table:
    half = (len(items) + 1) // 2
    left, right = items[:half], items[half:]
    rows = []
    for i in range(half):
        rows.append([Paragraph("• " + soft_wrap(left[i]), STYLES["Small"]),
                     Paragraph("• " + soft_wrap(right[i]), STYLES["Small"]) if i < len(right) else ""])
    t = Table(rows, colWidths=[W / 2, W / 2])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 0.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6),
    ]))
    return t


def build_appendix_flowables(payload: ReportPayload, issues: List[Issue], shown_items: int = 6) -> List[Flowable]:
    story: List[Flowable] = []
    long_issues = [(n, i) for n, i in enumerate(issues, 1) if len(i.items) > max(shown_items, 1)]

    pages = []
    jv = payload.journey_view or {}
    for p in jv.get("pages") or []:
        pages.append(p)
    if not pages:
        for p in (payload.analytics or {}).get("page_results") or []:
            pages.append({"url": p.get("url"), "title": "", "status": None})

    if not long_issues and not pages:
        return story

    story.append(PageBreak())
    story += section_intro("Appendix", "Full details",
                           "Reference lists behind the report. You don't need to read this part "
                           "unless you're fixing a specific issue.")

    if long_issues:
        story.append(Paragraph("Where the top issues were found", STYLES["H2"].clone("ap_h", spaceBefore=0)))
        for n, issue in long_issues:
            meta = SEVERITY_META[issue.severity]
            head = Paragraph(
                f'{n}. {esc(issue.title)} '
                f'<font color="{hexstr(TEXT_TERTIARY)}" size="8.5">· {esc(MODULE_LABELS.get(issue.module, issue.module))} · '
                f'<font color="{hexstr(meta["text"])}">{meta["label"]}</font> · {len(issue.items)} places</font>',
                STYLES["H3"].clone("ap_t", spaceBefore=3 * mm, spaceAfter=1.5 * mm))
            story.append(CondPageBreak(25 * mm))
            story.append(head)
            story.append(_two_col_list(issue.items))

    if pages:
        story.append(CondPageBreak(40 * mm))
        story.append(Paragraph("Pages scanned", STYLES["H2"]))
        rows = []
        for p in pages:
            status = p.get("status")
            rows.append([soft_wrap(short_url(p.get("url"), limit=80)), esc(p.get("title") or ""),
                         str(status) if status else "—"])
        story.append(data_table(["Page", "Title", "HTTP"], rows, [W - 98 * mm, 80 * mm, 18 * mm], align_right=(2,)))

    details = []
    cs = (payload.consent_view or {}).get("status") or {}
    if cs.get("scan_id"):
        details.append(["Consent scan", cs.get("scan_id"), (cs.get("scanned_at") or "")[:19].replace("T", " ")])
    if jv.get("scan_id"):
        details.append(["Journey scan", jv.get("scan_id"), (jv.get("started_at") or "")[:19].replace("T", " ")])
    rr = (payload.analytics or {}).get("runtime_result") or {}
    if rr.get("tested_at"):
        details.append(["Live analytics check", "—", rr["tested_at"][:19].replace("T", " ")])
    if details:
        story.append(CondPageBreak(30 * mm))
        story.append(Paragraph("Scan details", STYLES["H2"]))
        story.append(data_table(["Scan", "ID", "Started (UTC)"], details, [44 * mm, W - 88 * mm, 44 * mm]))
    return story
