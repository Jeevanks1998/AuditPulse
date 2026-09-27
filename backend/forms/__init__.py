"""
forms/

A dedicated, granular form-quality check package — one file per
concern — for a "forms" score that doesn't exist yet anywhere in the
pipeline (same situation ux/ and mobile/ describe: no
`breakdown["forms"] = ...` placeholder currently sitting in
services.audit_service.run_audit_pipeline to replace, so wiring this
in means adding a "forms" key to breakdown/EMPTY_BREAKDOWN rather than
swapping one out). Every check function returns findings in the same
{module, category, severity, title, description, recommendation} shape
services.audit_service / models.issue already persist, so it plugs
into Issue sync / report.html / history exactly like every other
module here.

Distinct from accessibility/labels.py, which asks whether a form
control has *any* accessible name — everything here assumes a label
exists and asks whether the form behaves and validates correctly:

    validation       — generic type="text" on fields that should use a
                        specific type; numeric inputs missing min/max;
                        forms with no client-side validation at all
    required_fields   — `required`/aria-required vs. the field's visual
                        "required" indicator, checked in both directions
    captcha           — bot-mitigation widget presence on sensitive
                        forms; deprecated reCAPTCHA v1 usage
    autocomplete      — missing autocomplete tokens on common identity/
                        contact/payment fields; autocomplete="off" on
                        password fields
    forms_score       — turns any list of these findings into a
                        weighted 0-100 score with a per-category
                        breakdown

Usage — wiring this into the real pipeline (crawler.crawler.Crawler
already produces a ParsedPage per page):

    from forms import run_page_checks, run_forms_checks

    findings = run_page_checks(page)
    result = score_forms(findings)

    # or in one call:
    result = run_forms_checks(page)

Pages with no <form> on them return an empty finding list from every
check here (see each module's early `if not forms: return []`), so
run_forms_checks on a form-free page scores every category at its
default 100 rather than being penalized for absence of data — the
same "no data, no penalty" convention seo_score.py and ux_score.py use.
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
    """
    Every form check for one already-fetched page. Cheap and
    synchronous — safe to call once per page during a crawl, same as
    ux/accessibility/seo's page-level checks.
    """
    findings: List[dict] = []
    findings += check_validation(page)
    findings += check_required_fields(page)
    findings += check_captcha(page)
    findings += check_autocomplete(page)
    return findings


def run_forms_checks(pages: List[ParsedPage]) -> FormsScoreResult:
    """
    Convenience entry point for a whole crawl: runs every page-level
    check across every page and scores the combined findings in one
    call. Pass a single-element list to score just the homepage.
    """
    findings: List[dict] = []
    for page in pages:
        findings += run_page_checks(page)
    return score_forms(findings)
