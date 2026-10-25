"""
Report exports, all built from one ReportPayload:
  generator.py      - ReportPayload, build_report_payload()
  json_report.py    - JSON export
  html_report.py    - HTML export
  evidence.py       - evidence ZIP
  report_storage.py - export cache on disk
  consent_view.py, journey_view.py, cookie_view.py - per-module views
The PDF is built from the same payload in pdf/.
"""

from reports.generator import ReportPayload, build_report_payload, build_score_grid
from reports.html_report import render_html_report
from reports.json_report import to_json_report

__all__ = [
    "ReportPayload",
    "build_report_payload",
    "build_score_grid",
    "render_html_report",
    "to_json_report",
]
