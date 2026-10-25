"""
Runs Google PageSpeed (category=accessibility), which uses axe-core rules
on the rendered page. Returns no findings, never an error, when there is no
API key or the call fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import httpx

from config.logging import logger
from config.settings import settings

MODULE = "accessibility"
CATEGORY = "axe"

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
REQUEST_TIMEOUT_SECONDS = 30.0  # Lighthouse runs can be slow

# Audits scoring below this (0-1) become findings.
FAILING_AUDIT_THRESHOLD = 0.9

# Rules that are WCAG A/AA failures (critical); others are warnings.
CRITICAL_AXE_RULES = {
    "color-contrast", "image-alt", "label", "button-name", "link-name",
    "aria-hidden-body", "aria-required-attr", "aria-valid-attr-value",
    "aria-valid-attr", "html-has-lang", "document-title", "frame-title",
    "input-image-alt", "object-alt", "video-caption",
}


@dataclass
class AxeAuditResult:
    findings: List[dict]
    category_score: Optional[int]  # Lighthouse's 0-100 accessibility score
    raw: Optional[dict]


async def fetch_axe_audit(
    client: httpx.AsyncClient,
    url: str,
    strategy: str = "mobile",
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> AxeAuditResult:
    """Calls PageSpeed for `url` and returns findings plus Lighthouse's score. Never raises."""
    if not settings.GOOGLE_PAGESPEED_API_KEY:
        logger.debug("accessibility.axe: no GOOGLE_PAGESPEED_API_KEY configured, skipping PSI call")
        return AxeAuditResult(findings=[], category_score=None, raw=None)

    params = {
        "url": url,
        "key": settings.GOOGLE_PAGESPEED_API_KEY,
        "strategy": strategy,
        "category": "accessibility",
    }

    try:
        response = await client.get(PSI_ENDPOINT, params=params, timeout=timeout)
        response.raise_for_status()
        raw = response.json()
    except httpx.HTTPError as exc:
        logger.warning(f"accessibility.axe: PSI request failed for {url}: {exc}")
        return AxeAuditResult(findings=[], category_score=None, raw=None)
    except ValueError as exc:  # response.json() failed
        logger.warning(f"accessibility.axe: PSI returned non-JSON for {url}: {exc}")
        return AxeAuditResult(findings=[], category_score=None, raw=None)

    return AxeAuditResult(
        findings=check_axe_audits(raw),
        category_score=_category_score(raw),
        raw=raw,
    )


def check_axe_audits(raw: Optional[dict]) -> List[dict]:
    """Findings for each failing accessibility audit. [] means unavailable, not "all passed"."""
    lighthouse = (raw or {}).get("lighthouseResult")
    if not lighthouse:
        return []

    category = (lighthouse.get("categories", {}) or {}).get("accessibility")
    if not category:
        return []

    audits = lighthouse.get("audits", {}) or {}
    findings: List[dict] = []

    for audit_ref in category.get("auditRefs", []):
        audit_id = audit_ref.get("id")
        audit = audits.get(audit_id)
        findings += _check_audit(audit_id, audit)

    return findings


def _check_audit(audit_id: Optional[str], audit: Optional[dict]) -> List[dict]:
    if not audit_id or not audit:
        return []
    score = audit.get("score")
    # None means "not applicable" (e.g. no images), which is a pass.
    if score is None or score >= FAILING_AUDIT_THRESHOLD:
        return []

    items = ((audit.get("details") or {}).get("items")) or []
    affected = len(items)
    severity = "critical" if audit_id in CRITICAL_AXE_RULES else "warning"
    title = audit.get("title", audit_id)
    description = (audit.get("description") or "").split(" [Learn")[0]  # drop the "Learn more" link
    affected_note = f" Affects {affected} element(s) on the page." if affected else ""

    return [_finding(
        severity,
        title,
        f"{description}{affected_note}".strip() or f"Axe rule \"{audit_id}\" failed.",
        recommendation=_RECOMMENDATIONS.get(audit_id),
    )]


def _category_score(raw: Optional[dict]) -> Optional[int]:
    lighthouse = (raw or {}).get("lighthouseResult")
    if not lighthouse:
        return None
    score = ((lighthouse.get("categories", {}) or {}).get("accessibility") or {}).get("score")
    return round(score * 100) if score is not None else None


_RECOMMENDATIONS = {
    "color-contrast": "Increase the contrast between text and its background to at least "
                       "4.5:1 (3:1 for large text).",
    "image-alt": "Add a descriptive alt attribute to every meaningful <img>, and alt=\"\" for "
                 "purely decorative ones.",
    "label": "Associate every form control with a <label> (or aria-label/aria-labelledby).",
    "button-name": "Give every <button> visible text, an aria-label, or an aria-labelledby "
                   "reference.",
    "link-name": "Give every link discernible text — visible text, an aria-label, or alt text "
                 "on a contained image.",
    "aria-hidden-body": "Never set aria-hidden=\"true\" on <body> — it hides the entire page "
                        "from assistive tech.",
    "html-has-lang": "Add a lang attribute to the <html> element (e.g. lang=\"en\").",
    "document-title": "Give the page a non-empty, descriptive <title>.",
    "tabindex": "Avoid positive tabindex values; use 0 or rely on natural DOM order.",
    "heading-order": "Don't skip heading levels — nest H2 under H1, H3 under H2, and so on.",
    "frame-title": "Give every <iframe>/<frame> a title attribute describing its content.",
    "duplicate-id-active": "Make every id attribute on active, focusable elements unique.",
    "aria-required-attr": "Add the ARIA attributes a given role requires (e.g. aria-checked "
                          "for role=\"checkbox\").",
    "aria-valid-attr-value": "Fix ARIA attribute values that don't match their expected type "
                             "(id reference, token, boolean, etc).",
    "aria-valid-attr": "Remove or correct ARIA attribute names that aren't valid.",
}


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
