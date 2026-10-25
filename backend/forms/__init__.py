"""
Form checks (not used by the audit pipeline yet):
  validation      - input types and min/max
  required_fields - `required` matches the visual "required" marker
  captcha         - bot protection on sensitive forms
  autocomplete    - autocomplete tokens on common fields
  forms_score     - 0-100 score
Pages without forms score 100.
"""

from __future__ import annotations

from typing import List

from crawler.parser import ParsedPage

from forms.autocomplete import check_autocomplete
from forms.captcha import check_captcha
from forms.forms_score import FormsScoreResult, score_forms
from forms.required_fields import check_required_fields
from forms.validation import check_validation

__all__ = [
    "check_validation",
    "check_required_fields",
    "check_captcha",
    "check_autocomplete",
    "score_forms",
    "FormsScoreResult",
    "run_page_checks",
    "run_forms_checks",
]


def run_page_checks(page: ParsedPage) -> List[dict]:
    """All form checks for one parsed page."""
    findings: List[dict] = []
    findings += check_validation(page)
    findings += check_required_fields(page)
    findings += check_captcha(page)
    findings += check_autocomplete(page)
    return findings


def run_forms_checks(pages: List[ParsedPage]) -> FormsScoreResult:
    """Runs every check on every page and scores the result."""
    findings: List[dict] = []
    for page in pages:
        findings += run_page_checks(page)
    return score_forms(findings)
