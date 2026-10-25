"""
PDF report (built with reportlab, no browser needed):
  cover.py         - page 1: scores, issue counts, summary
  overview.py      - page 2: top 5 to fix, what was checked, label key
  issues.py        - groups repeated findings into issues
  modules.py       - Consent / Analytics / Journey Map / Cookie sections
  scoring.py       - "How the scores work" page
  appendix.py      - full lists, pages scanned, scan IDs
  components.py    - shared pieces (pills, rings, bars, tables, images)
  theme.py         - colours, fonts, text styles
  pdf_generator.py - puts it all together
"""

from pdf.pdf_generator import generate_pdf_report

__all__ = ["generate_pdf_report"]
