"""
reports/

Report assembly and export, split by concern:

  generator.py      - builds the in-memory ReportPayload (score grid + findings + AI layer)
  json_report.py    - ReportPayload -> exportable JSON dict
  html_report.py    - ReportPayload -> standalone HTML document
  report_storage.py - on-disk caching of the JSON/HTML exports, keyed by audit id

services.report_service is the request-facing layer that calls into this
package; nothing under api/ should import from reports.* directly.
"""

from reports.generator import ReportPayload, ScoreCell, build_report_payload, build_score_grid
from reports.html_report import render_html_report
from reports.json_report import to_json_report

__all__ = [
    "ReportPayload",
    "ScoreCell",
    "build_report_payload",
    "build_score_grid",
    "render_html_report",
    "to_json_report",
]
