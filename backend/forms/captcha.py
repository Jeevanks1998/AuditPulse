"""
forms/captcha.py

Two narrow checks around bot protection on forms that are worth
protecting: (1) a form that collects credentials or contact info with
no recognizable CAPTCHA/bot-mitigation widget anywhere on the page,
and (2) a form still wired to the original reCAPTCHA v1 API, which
Google shut down (it stopped verifying new sites years ago). Detection
is pattern-based against known script src / widget markup — it can't
tell whether a detected CAPTCHA is actually configured correctly, only
whether one appears to be present at all.
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "forms"
CATEGORY = "captcha"

_SENSITIVE_FORM_HINT_RE = re.compile(
    r"login|log-in|sign-?in|sign-?up|register|contact|subscribe|newsletter|password|checkout",
    re.IGNORECASE,
)

_CAPTCHA_PATTERNS = {
    "reCAPTCHA v2/v3": re.compile(r"recaptcha/api\.js|g-recaptcha(?!-v1)", re.IGNORECASE),
    "hCaptcha": re.compile(r"hcaptcha\.com|h-captcha", re.IGNORECASE),
    "Cloudflare Turnstile": re.compile(r"challenges\.cloudflare\.com/turnstile|cf-turnstile", re.IGNORECASE),
    "FunCaptcha/Arkose": re.compile(r"funcaptcha|arkoselabs", re.IGNORECASE),
}

_DEPRECATED_RECAPTCHA_V1_RE = re.compile(r"recaptcha/api/challenge|recaptcha_ajax\.js", re.IGNORECASE)


def check_captcha(page: ParsedPage) -> List[dict]:
    """Findings for missing bot protection on sensitive forms and deprecated CAPTCHA usage."""
    forms = page.soup.find_all("form")
    if not forms:
        return []

    page_html = str(page.soup)
    findings: List[dict] = []
    findings += _check_deprecated_recaptcha_v1(page, page_html)
    findings += _check_missing_captcha(page, forms, page_html)
    return findings


def _check_deprecated_recaptcha_v1(page: ParsedPage, page_html: str) -> List[dict]:
    if not _DEPRECATED_RECAPTCHA_V1_RE.search(page_html):
        return []

    return [_finding(
        "critical",
        "Page references the deprecated reCAPTCHA v1 API",
        f"{page.url} loads reCAPTCHA v1 endpoints, an API Google retired years ago. It no "
        "longer verifies challenges, so any form depending on it for bot protection is "
        "effectively unprotected regardless of whether the widget still renders.",
        recommendation="Migrate to reCAPTCHA v2/v3, hCaptcha, or Cloudflare Turnstile.",
    )]


def _check_missing_captcha(page: ParsedPage, forms: list, page_html: str) -> List[dict]:
    detected = _detect_captcha_providers(page_html)
    if detected:
        return []

    sensitive_forms = 0
    for form in forms:
        identity = " ".join(filter(None, [
            form.get("id"), form.get("name"), form.get("action"), form.get("class", [""])[0] if form.get("class") else "",
        ]))
        has_sensitive_field = bool(form.find_all("input", attrs={"type": ["password", "email"]}))
        if _SENSITIVE_FORM_HINT_RE.search(identity) or has_sensitive_field:
            sensitive_forms += 1

    if not sensitive_forms:
        return []

    return [_finding(
        "info",
        "No CAPTCHA or bot-mitigation widget detected on a sensitive form",
        f"{page.url} has {sensitive_forms} form(s) that look like login, signup, contact, or "
        "similar (by field type or form identity), but no recognizable CAPTCHA/bot-"
        "mitigation script (reCAPTCHA, hCaptcha, Turnstile, FunCaptcha) was found on the "
        "page. Forms like these are common targets for automated spam and credential-"
        "stuffing traffic.",
        recommendation="Add a CAPTCHA or equivalent bot-mitigation step to forms that "
                        "collect credentials or contact info, or confirm equivalent "
                        "protection is applied at the server/WAF level instead.",
    )]


def _detect_captcha_providers(page_html: str) -> List[str]:
    return [name for name, pattern in _CAPTCHA_PATTERNS.items() if pattern.search(page_html)]


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
