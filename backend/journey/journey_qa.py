"""
Journey health numbers and findings, from measurements only.

Critical: conversion not tracked, broken important CTA, download not working,
no analytics anywhere. Warning: form not tracked, important page without
analytics, duplicate event, inconsistent tracking, unexpected navigation.
Info: form submit not verifiable without submitting, and similar.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from journey.journey_interactions import (
    APPOINTMENT,
    CLASS_LABELS,
    CONVERSION_CLASSES,
    CTA,
    DOWNLOAD,
    EMAIL,
    FORM,
    FORM_SUBMIT,
    LOGIN,
    PHONE,
    PURCHASE,
    SIGNUP,
    Interaction,
)

MODULE = "journey"
_CRITICAL_GAP_CLASSES = {CTA, DOWNLOAD, SIGNUP, APPOINTMENT, PURCHASE}
_GA4_DOWNLOAD_PARAMS = ("file_name", "file_extension", "link_url")


def _shot(it: Interaction) -> Optional[str]:
    s = it.screenshots or {}
    return s.get("highlighted") or s.get("before") or s.get("after")


def _finding(severity: str, category: str, title: str, it: Optional[Interaction], description: str,
             recommendation: str, observed: str = "", tracking: str = "", page: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": category,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
        "affected_urls": [page or (it.page_url if it else "")] if (page or it) else [],
        "journey": {
            "page": page or (it.page_url if it else None),
            "interaction": it.label if it else None,
            "interaction_index": it.index if it else None,
            "interaction_type": it.classification_label if it else None,
            "evidence": it.observed if it else observed,
            "observed_behavior": observed or (it.observed if it else ""),
            "tracking_behavior": tracking,
            "screenshot": _shot(it) if it else None,
            "screenshots": (it.screenshots if it else {}),
        },
    }


def _path(url: Optional[str]) -> str:
    from urllib.parse import urlparse
    if not url:
        return ""
    p = urlparse(url)
    return (p.path or "/") if p.scheme in ("http", "https") else url


def _names(interactions: List[Interaction]) -> Dict[int, str]:
    """Unique readable names, e.g. "Learn more -> /pricing" when several share the same text."""
    counts: Dict[str, int] = {}
    for it in interactions:
        counts[it.label] = counts.get(it.label, 0) + 1
    names = {}
    for it in interactions:
        name = it.label or CLASS_LABELS.get(it.classification, "Element")
        if counts.get(it.label, 0) > 1 and it.destination and it.classification != FORM:
            name = f"{name} → {_path(it.destination)}"
        names[it.index] = name
    return names


def _events_text(it: Interaction) -> str:
    evs = (it.tracking or {}).get("events") or []
    if not evs:
        lc = (it.tracking or {}).get("lifecycle_events") or []
        return ("No interaction event observed"
                + (f" (only lifecycle: {', '.join(sorted({e.get('event') or '' for e in lc}))})" if lc else "") + ".")
    def one(e: dict) -> str:
        kind = "dataLayer event" if e.get("source") == "dataLayer" else "analytics hit"
        return f"{e.get('vendor_label')} “{e.get('event')}” ({kind})"
    return "Observed: " + ", ".join(one(e) for e in evs[:5]) + "."


def compute_health(interactions: List[Interaction], pages_count: int, forms_count: int) -> dict:
    unique = [i for i in interactions if i.duplicate_of is None]
    tested = [i for i in unique if i.tested]
    successful = [i for i in tested if i.status == "success"]
    tracked = [i for i in tested if (i.tracking or {}).get("status") in ("tracked", "duplicate")]
    gaps = [i for i in tested if i.status == "success" and (i.tracking or {}).get("status") == "not_tracked"
            and (i.classification in CONVERSION_CLASSES or i.classification == FORM)]
    evidence = [i for i in unique if (i.screenshots or {}).get("highlighted") or (i.screenshots or {}).get("before")]
    conv_tested = [i for i in tested if i.status == "success"
                   and (i.classification in CONVERSION_CLASSES or i.classification == FORM)]
    conv_tracked = [i for i in conv_tested if (i.tracking or {}).get("status") in ("tracked", "duplicate")]

    counts = {
        "pages_scanned": pages_count,
        "interactions_discovered": len(unique),
        "interactions_total_including_repeats": len(interactions),
        "interactions_tested": len(tested),
        "successful_interactions": len(successful),
        "tracked_interactions": len(tracked),
        "tracking_gaps": len(gaps),
        "evidence_captured": len(evidence),
        "skipped_for_safety": len([i for i in unique if i.status == "skipped"]),
        "consent_controls": len([i for i in unique if i.status == "consent_control"]),
        "forms": forms_count,
        "downloads": len([i for i in unique if i.classification == DOWNLOAD]),
        "ctas": len([i for i in unique if i.classification == CTA]),
        "dynamic_elements": len([i for i in unique if i.dynamic]),
    }
    by_type: Dict[str, int] = {}
    for i in unique:
        by_type[i.classification_label] = by_type.get(i.classification_label, 0) + 1

    if not tested:
        score = None
        rates = {"success_rate": None, "conversion_tracking_coverage": None, "evidence_rate": None}
    else:
        success_rate = len(successful) / len(tested)
        coverage = (len(conv_tracked) / len(conv_tested)) if conv_tested else 1.0
        evidence_rate = min(1.0, len([i for i in tested if (i.screenshots or {}).get("highlighted")
                                      or (i.screenshots or {}).get("before")]) / len(tested))
        score = round(100 * (0.35 * success_rate + 0.45 * coverage + 0.20 * evidence_rate))
        rates = {"success_rate": round(success_rate, 3), "conversion_tracking_coverage": round(coverage, 3),
                 "evidence_rate": round(evidence_rate, 3)}
    return {"counts": counts, "by_type": by_type, "rates": rates, "score": score}


def build_findings(interactions: List[Interaction], pages_meta: List[dict], analytics_present: bool,
                   forms_by_id: Dict[str, dict]) -> List[dict]:
    findings: List[dict] = []
    unique = [i for i in interactions if i.duplicate_of is None]
    tested = [i for i in unique if i.tested]
    names = _names(unique)
    conv_tested = [i for i in tested if i.classification in CONVERSION_CLASSES or i.classification == FORM]

    if not analytics_present and conv_tested:
        findings.append(_finding(
            "critical", "tracking", "No analytics activity observed anywhere in the journey", None,
            f"{len(conv_tested)} conversion-type interaction(s) were tested across the site, but no analytics "
            "request (GA4, GTM, Adobe, Piano, Meta…) or dataLayer event was observed at any point.",
            "Install / enable the analytics implementation, then re-run the audit.",
            observed="No analytics vendor traffic during the scan.", tracking="None",
            page=unique[0].page_url if unique else None))

    for it in tested:
        tr = it.tracking or {}
        status = tr.get("status")
        kind = it.classification
        label = CLASS_LABELS.get(kind, kind)
        name = names.get(it.index, it.label)

        # Broken / not working
        if it.status == "failed":
            if kind == DOWNLOAD:
                findings.append(_finding(
                    "critical", "downloads", f"Download inaccessible: {name}", it,
                    f"The download “{it.label}” on {it.page_url} points to {it.destination}, which "
                    + (f"responded HTTP {it.http_status}." if it.http_status else "could not be reached."),
                    "Fix the file URL or remove the link.", tracking=_events_text(it)))
            elif it.outcome == "contact_link_activated":
                # A phone / e-mail link whose address is written wrongly: phones may not dial it.
                findings.append(_finding(
                    "warning", "contact", f"Contact link address looks malformed: {name}", it,
                    f"“{it.label}” on {it.page_url} points to {it.destination}. {it.observed}",
                    "Write phone links as tel:+<country code><number> and e-mail links as mailto:name@domain.",
                    tracking=_events_text(it)))
            elif kind in (CTA, SIGNUP, APPOINTMENT, LOGIN) or it.importance >= 3:
                findings.append(_finding(
                    "critical", "cta", f"Important {label} does not work: {name}", it,
                    f"“{it.label}” on {it.page_url} was clicked in a real browser. {it.observed}",
                    (f"The link leads to an error page (HTTP {it.http_status}): fix the destination or remove the link."
                     if it.outcome == "broken_destination" else
                     "Open the page and click it yourself: if it really does nothing, fix its link or click "
                     "handler so it takes the visitor where it promises."), tracking=_events_text(it)))
            elif it.outcome == "no_visible_effect":
                findings.append(_finding(
                    "info", "verification", f"Interaction difficult to verify: {name}", it,
                    f"“{it.label}” ({label}) on {it.page_url} was clicked but produced no observable "
                    "navigation, dialog, expansion or content change.",
                    "Check whether the control is functional; give it a clear, observable result.",
                    tracking=_events_text(it)))
            continue

        if it.outcome == "unexpected_navigation":
            findings.append(_finding(
                "info", "navigation", f"Link lands on a different page than its address: {name}", it,
                f"“{it.label}” on {it.page_url} links to {_path(it.destination)} but the visitor ends up on "
                f"{_path(it.final_url)} (moved by the site's own scripts). {it.observed}",
                "Point the link straight at the final page so visitors and analytics see one consistent URL.",
                tracking=_events_text(it)))

        if status == "not_tracked" and it.status == "success":
            if kind in _CRITICAL_GAP_CLASSES:
                # Real conversions (sign-up, purchase, booking, download) and the page's most important
                # CTAs are critical; an ordinary CTA without its own event is a warning.
                gap_sev = "critical" if (kind != CTA or it.importance >= 3) else "warning"
                findings.append(_finding(
                    gap_sev, "tracking", f"Not tracked: {label} “{name}”", it,
                    f"“{it.label}” ({label}) on {it.page_url} was clicked and worked, but no analytics tool "
                    "received anything for the click and no dataLayer event was pushed.",
                    f"Add an analytics event for this {label.lower()} (e.g. a GA4 event via GTM) and verify it fires on click.",
                    tracking=_events_text(it)))
            elif kind in (PHONE, EMAIL, LOGIN):
                findings.append(_finding(
                    "warning", "tracking", f"Not tracked: {label} “{name}”", it,
                    f"“{it.label}” on {it.page_url} was activated, but no analytics event was observed.",
                    f"Track {label.lower()} clicks as a lead/engagement event.", tracking=_events_text(it)))
            elif kind == FORM:
                findings.append(_finding(
                    "warning", "forms", f"Form start not tracked: {name}", it,
                    f"The form “{it.label}” on {it.page_url} was clicked and typed into (not submitted), but "
                    "no form_start / form interaction event was sent.",
                    "Track form starts (GA4 enhanced measurement or a GTM form trigger).", tracking=_events_text(it)))

        if status == "tracked" and it.status == "success" and analytics_present \
                and (kind in CONVERSION_CLASSES or kind == FORM):
            sources = {e.get("source") for e in (tr.get("events") or [])}
            if sources == {"dataLayer"}:
                dl_events = sorted({e.get("event") for e in (tr.get("events") or []) if e.get("event")})
                findings.append(_finding(
                    "info", "tracking", f"Click reaches the dataLayer only: {name}", it,
                    f"Clicking “{it.label}” ({label}) on {it.page_url} pushed "
                    f"{', '.join(dl_events[:3]) or 'a dataLayer event'} to the dataLayer, but no analytics tool "
                    "(GA4, Adobe, Piano, Meta…) received a request for it within a few seconds.",
                    "Check that a tag in your tag manager forwards this dataLayer event to your analytics tool.",
                    tracking=_events_text(it)))

        if status == "duplicate":
            findings.append(_finding(
                "warning", "tracking", f"Counted twice: {name}", it,
                f"One activation of “{it.label}” on {it.page_url} sent the same event more than once: "
                f"{', '.join(tr.get('duplicates') or [])}.",
                "Remove the duplicate tag/trigger so each interaction is counted once.", tracking=_events_text(it)))

        if kind == DOWNLOAD and status in ("tracked", "duplicate"):
            ga4 = [e for e in tr.get("events") or [] if e.get("vendor") == "ga4"]
            if ga4 and not any(any(p in (e.get("params") or {}) for p in _GA4_DOWNLOAD_PARAMS) for e in ga4):
                findings.append(_finding(
                    "info", "tracking", f"Missing optional parameter on download event: {name}", it,
                    f"The GA4 event for “{it.label}” carries none of {', '.join(_GA4_DOWNLOAD_PARAMS)}.",
                    "Send file_name / file_extension / link_url with download events.", tracking=_events_text(it)))

    # Forms are never submitted on live sites.
    for it in unique:
        if it.classification == FORM_SUBMIT:
            form = forms_by_id.get(it.form_id or "") or {}
            if not it.visible or (form and not form.get("visible", True)):
                continue          # hidden form: not part of a visitor journey
            hints = form.get("tracking_hints") or []
            findings.append(_finding(
                "info", "forms", f"Form submission tracking not verifiable without submitting: {it.label}", it,
                f"The submit control “{it.label}” on {it.page_url} was discovered but not clicked (production "
                "safety)." + (f" Static tracking hints on the form: {', '.join(hints)}." if hints else
                              " No tracking hint was found on the form element itself."),
                "Verify form_submit / generate_lead tracking in a controlled test environment.",
                tracking="Not tested — submission not executed."))

    # Inconsistent tracking within one interaction type.
    by_kind: Dict[str, Dict[str, List[Interaction]]] = {}
    for it in tested:
        st = (it.tracking or {}).get("status")
        # Only the interactions that matter (importance 2+) are compared; minor UI controls would add noise.
        if it.status == "success" and st in ("tracked", "duplicate", "not_tracked") and it.importance >= 2:
            by_kind.setdefault(it.classification, {}).setdefault("t" if st != "not_tracked" else "n", []).append(it)
    for kind, groups in by_kind.items():
        if groups.get("t") and groups.get("n") and kind in CONVERSION_CLASSES | {FORM}:
            # A summary of gaps already listed one by one above: an insight, not another issue to fix.
            findings.append(_finding(
                "info", "tracking", f"Tracking inconsistency across {CLASS_LABELS.get(kind, kind)} interactions", None,
                f"{len(groups['t'])} {CLASS_LABELS.get(kind, kind)} interaction(s) are tracked "
                f"({', '.join(names.get(i.index, i.label) for i in groups['t'][:3])}) but {len(groups['n'])} send nothing "
                f"({', '.join(names.get(i.index, i.label) for i in groups['n'][:3])}).",
                "Apply the same tracking to every interaction of this type.",
                observed="Mixed: analytics detected / not detected", tracking="Inconsistent", page=groups["n"][0].page_url))

    # Journey pages with no analytics at all.
    if analytics_present:
        for pm in pages_meta:
            if pm.get("loaded") and not pm.get("analytics_on_load"):
                findings.append(_finding(
                    "warning", "tracking", f"Important journey step missing analytics: {pm.get('path')}", None,
                    f"The page {pm.get('url')} is part of the discovered journey but sent no analytics "
                    "request or dataLayer event when it loaded.",
                    "Make sure the analytics tag is present on every page of the journey.",
                    observed="Page loaded without analytics activity", tracking="None on page load",
                    page=pm.get("url")))
    return findings
