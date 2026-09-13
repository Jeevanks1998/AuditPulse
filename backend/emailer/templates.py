"""
emailer/templates.py

Builds the auto-generated Subject + editable body for the "Send to POC"
email (§9.3), straight off the same ReportPayload every other export
reads (§8) — no separate/duplicated scoring or detection logic, and
nothing here is hardcoded per §14 ("Do not hardcode vendor-specific
results"): platform names and every status line are pulled from
`payload.analytics` / `payload.consent`, so a payload with no analytics
module run just prints "Not tested" rather than a fabricated pass.

The frontend always shows these as *editable* fields (§9.1) — this
module only supplies sensible starting text.
"""

from __future__ import annotations

from reports.generator import ReportPayload

_TEMPLATE = """Hi {poc_name},

Please find attached the latest AuditPulse website audit report for:

Website: {url}
Audit Date: {date}
Overall Score: {score}/100

Key areas reviewed:
• SEO
• Performance
• Accessibility
• Analytics
• Consent & Cookie Compliance
• Security
• UX

Analytics Summary:
• Detected platforms: {platforms}
• Page View validation: {page_view_status}
• Scroll validation: {scroll_status}
• Click validation: {click_status}

Consent Summary:
• Consent banner: {banner_status}
• Accept / Reject / Personalize: {accept_reject_status}
• Pre-consent tracking: {pre_consent_tracking}
• Pre-consent cookies: {pre_consent_cookies}

The detailed report and supporting evidence are attached for review.

Please let us know if any clarification is required.

Regards,
{user_name}
AuditPulse"""


def build_subject(payload: ReportPayload) -> str:
    return f"Website Audit Report — {payload.url}"


def build_body(payload: ReportPayload, *, poc_name: str = "there", user_name: str = "AuditPulse") -> str:
    analytics = payload.analytics or {}
    consent = payload.consent or {}
    runtime = consent.get("runtime_result") or {}

    return _TEMPLATE.format(
        poc_name=poc_name or "there",
        url=payload.url,
        date=(payload.generated_at or "")[:10] or "—",
        score=payload.overall,
        platforms=", ".join(analytics.get("trackers_detected") or []) or "None detected",
        page_view_status=_vendor_status_summary(analytics, "page_view_status"),
        scroll_status=_vendor_status_summary(analytics, "scroll_status"),
        click_status=_vendor_status_summary(analytics, "click_status"),
        banner_status="Detected" if consent.get("has_cookie_banner") else "Not detected",
        accept_reject_status=_consent_runtime_summary(runtime),
        pre_consent_tracking=(
            "Blocked" if consent.get("banner_blocks_scripts_pre_consent") else "Tracking found before consent"
        ) if consent else "Not tested",
        pre_consent_cookies=_pre_consent_cookie_summary(payload),
        user_name=user_name or "AuditPulse",
    )


def _vendor_status_summary(analytics: dict, status_key: str) -> str:
    if not analytics or not analytics.get("runtime_tested"):
        return "Not tested"
    vendors = ((analytics.get("runtime_result") or {}).get("vendors") or {}).values()
    if not vendors:
        return "Not tested"
    statuses = [v.get(status_key) for v in vendors if v.get(status_key) not in (None, "not_applicable")]
    if not statuses:
        return "Not applicable"
    if all(s == "passed" for s in statuses):
        return "Passed"
    if any(s == "failed" for s in statuses):
        return f"Failed ({statuses.count('failed')}/{len(statuses)} vendor(s))"
    return "Partial"


def _consent_runtime_summary(runtime: dict) -> str:
    if not runtime:
        return "Not tested"
    bits = []
    if runtime.get("accept_clicked"):
        bits.append("Accept OK")
    if runtime.get("reject_clicked"):
        bits.append("Reject OK")
    if runtime.get("manage_clicked"):
        bits.append("Personalize OK")
    return ", ".join(bits) if bits else "Not tested"


def _pre_consent_cookie_summary(payload: ReportPayload) -> str:
    cookies = payload.cookie_evidence.get("before_consent")
    if cookies is None:
        return "Not tested"
    return f"{len(cookies)} cookie(s) found before consent" if cookies else "None found before consent"
