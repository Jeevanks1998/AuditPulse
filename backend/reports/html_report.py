"""
reports/html_report.py

Renders a ReportPayload (§8) into one self-contained HTML document —
api/reports.py's `/{audit_id}/export.html`, cached to disk via
reports/report_storage.py's save_html/load_html. Mirrors the section
order pdf/pdf_generator.py uses (cover -> executive summary -> critical
findings -> score grid -> business impact -> action plan -> full
findings appendix), just as plain HTML/CSS instead of ReportLab
flowables.

Every finding/summary/AI string here can originate from an AI provider or
a crawled page, so everything user/AI-derived goes through `html.escape`
before landing in the markup — the same trust boundary pdf/theme.py's
`esc` helper exists for on the PDF side.
"""

from __future__ import annotations

from html import escape as esc
from typing import List

from reports.generator import ReportPayload

_SEVERITY_LABELS = {"critical": "Critical", "warning": "Warning", "info": "Info"}


def render_html_report(payload: ReportPayload) -> str:
    sections = [
        _render_head(payload),
        "<body>",
        _render_header(payload),
        _render_executive_summary(payload),
        _render_score_grid(payload),
        _render_critical_findings(payload),
        _render_business_impact(payload),
        _render_action_plan(payload),
        _render_all_findings(payload),
        "</body></html>",
    ]
    return "\n".join(section for section in sections if section)


def _render_head(payload: ReportPayload) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<title>Audit Report — {esc(payload.url)}</title>"
        "<style>"
        "body{font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:900px;"
        "margin:0 auto;padding:32px 24px;color:#0F172A;line-height:1.5}"
        "h1{font-size:28px;margin-bottom:4px}"
        "h2{font-size:20px;margin-top:36px;border-bottom:2px solid #E2E8F0;padding-bottom:6px}"
        ".muted{color:#64748B}"
        ".cards{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}"
        ".card{border:1px solid #E2E8F0;border-radius:8px;padding:14px 18px;min-width:120px;text-align:center}"
        ".card .value{font-size:22px;font-weight:700}"
        ".card .label{font-size:11px;text-transform:uppercase;color:#64748B;margin-top:4px}"
        "table{width:100%;border-collapse:collapse;margin:12px 0}"
        "th,td{border:1px solid #E2E8F0;padding:8px 10px;text-align:left;font-size:14px;vertical-align:top}"
        "th{background:#0F172A;color:#fff}"
        "tr:nth-child(even){background:#F8FAFC}"
        ".severity-critical{color:#DC2626;font-weight:700}"
        ".severity-warning{color:#D97706;font-weight:700}"
        ".severity-info{color:#2563EB;font-weight:700}"
        "</style></head>"
    )


def _render_header(payload: ReportPayload) -> str:
    weakest = payload.weakest_module
    weakest_text = f"{esc(weakest.label)} ({weakest.score}/100)" if weakest else "N/A"
    return (
        "<header>"
        f"<h1>Website Audit Report</h1>"
        f"<p class=\"muted\">{esc(payload.url)} &middot; generated {esc(payload.generated_at)}</p>"
        "<div class=\"cards\">"
        f"<div class=\"card\"><div class=\"value\">{payload.overall}/100</div><div class=\"label\">Overall Score</div></div>"
        f"<div class=\"card\"><div class=\"value\">{esc(payload.overall_status)}</div><div class=\"label\">Status</div></div>"
        f"<div class=\"card\"><div class=\"value\">{(payload.severity_counts or {}).get('critical', 0)}</div><div class=\"label\">Critical</div></div>"
        f"<div class=\"card\"><div class=\"value\">{len(payload.findings)}</div><div class=\"label\">Total Findings</div></div>"
        f"<div class=\"card\"><div class=\"value\">{weakest_text}</div><div class=\"label\">Weakest Module</div></div>"
        "</div></header>"
    )


def _render_executive_summary(payload: ReportPayload) -> str:
    if not payload.executive_summary:
        return ""
    return f"<h2>Executive Summary</h2><p>{esc(payload.executive_summary)}</p>"


def _render_score_grid(payload: ReportPayload) -> str:
    if not payload.score_grid:
        return ""
    rows = "".join(
        f"<tr><td>{esc(cell.label)}</td><td>{cell.score}/100</td></tr>" for cell in payload.score_grid
    )
    return f"<h2>Score Breakdown</h2><table><tr><th>Module</th><th>Score</th></tr>{rows}</table>"


def _render_critical_findings(payload: ReportPayload) -> str:
    critical = [f for f in payload.findings if f.get("severity") == "critical"]
    if not critical:
        return ""
    rows = "".join(
        f"<tr><td>{esc((f.get('module') or '').replace('_', ' ').title())}</td>"
        f"<td><b>{esc(f.get('title', ''))}</b><br><span class=\"muted\">{esc(f.get('description', ''))}</span></td></tr>"
        for f in critical
    )
    return f"<h2>Critical Findings</h2><table><tr><th>Module</th><th>Finding</th></tr>{rows}</table>"


def _render_business_impact(payload: ReportPayload) -> str:
    if not payload.business_impact:
        return ""
    rows = "".join(
        f"<tr><td>{esc(item.get('title', ''))}</td>"
        f"<td class=\"severity-{esc(item.get('severity', 'info'))}\">{esc(_SEVERITY_LABELS.get(item.get('severity'), 'Info'))}</td>"
        f"<td>{esc(item.get('impact', ''))}</td></tr>"
        for item in payload.business_impact
    )
    return f"<h2>Business Impact</h2><table><tr><th>Finding</th><th>Severity</th><th>Impact</th></tr>{rows}</table>"


def _render_action_plan(payload: ReportPayload) -> str:
    plan = payload.action_plan
    if not plan:
        return ""
    horizons = (("Quick Wins", plan.quick_wins), ("Short Term", plan.short_term), ("Long Term", plan.long_term))
    blocks: List[str] = []
    for title, steps in horizons:
        if not steps:
            continue
        items = "".join(f"<li>{esc(step.get('step', step.get('title', '')))}</li>" for step in steps)
        blocks.append(f"<h3>{esc(title)}</h3><ul>{items}</ul>")
    if not blocks:
        return ""
    return "<h2>Action Plan</h2>" + "".join(blocks)


def _render_all_findings(payload: ReportPayload) -> str:
    if not payload.findings:
        return ""
    rows = "".join(
        f"<tr><td>{esc((f.get('module') or '').replace('_', ' ').title())}</td>"
        f"<td class=\"severity-{esc(f.get('severity', 'info'))}\">{esc(_SEVERITY_LABELS.get(f.get('severity'), 'Info'))}</td>"
        f"<td><b>{esc(f.get('title', ''))}</b><br><span class=\"muted\">{esc(f.get('description', ''))}</span></td></tr>"
        for f in payload.findings
    )
    return f"<h2>All Findings ({len(payload.findings)})</h2><table><tr><th>Module</th><th>Severity</th><th>Finding</th></tr>{rows}</table>"


__all__ = ["render_html_report"]
