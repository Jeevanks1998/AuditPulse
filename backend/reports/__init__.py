"""
reports/

The report export pipeline (§8: "one canonical data model for
dashboard/report/PDF/email"):

  generator.py       - ReportPayload + build_report_payload() / build_score_grid()
  json_report.py     - to_json_report(payload) -> dict (api/reports.py's export.json)
  html_report.py     - render_html_report(payload) -> str (export.html)
  evidence.py         - build_evidence_zip() / evidence_zip_filename() (evidence.zip)
  report_storage.py  - on-disk cache for the three export formats above

pdf/pdf_generator.py (a sibling package, not part of this one, since it
depends on ReportLab) builds the fourth export format from the same
ReportPayload.

services.report_service is the only caller that should reach into this
package — it has no idea SQLAlchemy or FastAPI exist, and nothing under
api/ should import from reports.* directly.
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
