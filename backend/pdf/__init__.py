"""
pdf/

Binary PDF export for a completed audit's report, split by concern the
same way reports/ is:

  cover.py           - title page (URL, overall score ring, generated date)
  summary.py         - executive summary + top-priorities highlights
  charts.py          - score breakdown as a radar chart + bar chart
  screenshots.py     - embeds the captured homepage screenshot, if any
  recommendations.py - business impact + action plan (quick/short/long term)
  appendix.py         - full findings table
  pdf_generator.py   - assembles all of the above into one PDF (public entry point)
  theme.py           - shared colors/fonts/paragraph styles used across this package

Built on reportlab (vector drawing + Platypus flowables) rather than an
HTML-to-PDF renderer — no browser engine, no extra system dependency
(unlike weasyprint, which needs Cairo/Pango) — so it composes cleanly
with the AI-derived data already living on a
reports.generator.ReportPayload.

services.report_service is the request-facing layer that calls into
this package (mirroring how it calls into reports/); nothing under api/
should import from pdf.* directly.
"""

from pdf.pdf_generator import generate_pdf_report

__all__ = ["generate_pdf_report"]
