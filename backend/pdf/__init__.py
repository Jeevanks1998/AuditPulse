"""
pdf/

Binary PDF export for a completed audit's report, split by concern the
same way reports/ is:

  cover.py         - page 1: header band, overall + module scores, issue counts, summary
  overview.py      - page 2 "Start here": top 5 to fix, what was checked, label key
  issues.py        - groups raw findings into distinct issues (repeats counted once)
  modules.py       - Consent / Analytics / Customer Journey evidence sections
  appendix.py      - full affected-place lists, pages scanned, scan IDs
  components.py    - shared building blocks (pills, rings, bars, tables, images)
  theme.py         - palette, Source Sans 3 fonts, paragraph styles
  pdf_generator.py - assembles all of the above (public entry point)

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
