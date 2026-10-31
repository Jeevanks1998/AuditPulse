"""
One consent view used everywhere (report page, dashboard, PDF, JSON, ZIP), so
they always show the same evidence: status, headline tiles, laws (assessed or
not), banner buttons, requests and cookies before consent, screenshots, scan
steps. Plain dicts in and out. Older audits still render (legacy=True).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_FRAMEWORKS = (("gdpr", "GDPR + ePrivacy"), ("ccpa", "CCPA / CPRA"), ("dpdp", "India DPDP Act 2023"))

# Required checks per law (the browser-only check is excluded, as in consent_score).
_GDPR_REQUIRED = (
    "consent_banner", "accept_control", "reject_control", "reject_parity",
    "trackers_blocked_pre_consent", "cookies_blocked_pre_consent", "consent_is_granular",
    "privacy_policy_available", "consent_withdrawal_available",
)
_CCPA_REQUIRED = ("privacy_policy_available", "privacy_choices_link", "do_not_sell_link",
                  "opt_out_mechanism", "gpc_honored")

CHECK_LABELS = {
    "consent_banner": "Consent banner",
    "accept_control": "Accept control",
    "reject_control": "Reject control",
    "reject_parity": "Reject parity",
    "trackers_blocked_pre_consent": "No tracking before consent",
    "cookies_blocked_pre_consent": "No analytics/marketing cookies before consent",
    "consent_is_granular": "Consent is granular (preferences panel)",
    "privacy_policy_available": "Privacy policy available",
    "consent_withdrawal_available": "Consent withdrawal available",
    "reject_blocks_tracking": "Reject actually blocks tracking",
    "privacy_choices_link": '"Your Privacy Choices" link',
    "do_not_sell_link": '"Do Not Sell or Share" link',
    "opt_out_mechanism": "Opt-out mechanism reachable",
    "gpc_honored": "Global Privacy Control handling",
    "opt_out_behavior_verified": "Opt-out actually stops tracking",
}

_NET_ORDER = ["ANALYTICS", "ADVERTISING", "TAG_MANAGER", "SOCIAL", "CMP",
              "OTHER_THIRD_PARTY", "CONTENT_CDN", "FONT", "FIRST_PARTY", "UNKNOWN"]

_COOKIE_GROUPS = (
    ("consent_required", "Analytics / marketing", "fail"),
    ("consent_management", "Consent management (CMP storage)", "info"),
    ("essential", "Essential / security", "pass"),
    ("functional", "Functional", "info"),
    ("unknown", "Unknown — needs review (not a failure)", "neutral"),
)

_SCREENSHOT_SLOTS = (
    ("initial", "Initial banner", "banner_screenshot_url"),
    ("preferences", "Preferences panel", "preferences_screenshot_url"),
    ("reject", "After Reject", "reject_screenshot_url"),
    ("accept", "After Accept", "accept_screenshot_url"),
)


_CMP_HINTS = (
    ("onetrust", "OneTrust"), ("cybotcookiebot", "Cookiebot"), ("cky-", "CookieYes"), ("osano", "Osano"),
    ("truste", "TrustArc"), ("consent_blackbar", "TrustArc"), ("qc-cmp", "Quantcast Choice"),
    ("iubenda", "iubenda"), ("cmplz", "Complianz"), ("didomi", "Didomi"), ("usercentrics", "Usercentrics"),
    ("uc-center", "Usercentrics"), ("axeptio", "Axeptio"), ("cookiefirst", "CookieFirst"),
    ("cookie-law-info", "CookieYes / GDPR Cookie Consent"), ("cli-modal", "CookieYes / GDPR Cookie Consent"),
    ("cc-window", "Cookie Consent"), ("cc-banner", "Cookie Consent"), ("borlabs", "Borlabs Cookie"),
    ("tarteaucitron", "tarteaucitron"), ("fc-consent", "Google Funding Choices"), ("sp_message", "Sourcepoint"),
    ("privacy-mgmt", "Sourcepoint"), ("cmpbox", "consentmanager"), ("cmpwrapper", "consentmanager"),
    ("termly", "Termly"), ("trustarc", "TrustArc"), ("cookielaw", "OneTrust"),
    ("tc-privacy", "TrustCommander (Commanders Act)"), ("footer_tc_privacy", "TrustCommander (Commanders Act)"),
    ("trustcommander", "TrustCommander (Commanders Act)"), ("cookiehub", "CookieHub"), ("klaro", "Klaro"),
    ("_evidon", "Evidon (Crownpeak)"), ("evidon", "Evidon (Crownpeak)"),
    ("cookie-script", "CookieScript"), ("cookiescript", "CookieScript"), ("ketch", "Ketch"),
)


def _cmp_from_network(network: Optional[dict]) -> Optional[str]:
    """Consent tool whose servers the page contacted, most requests first."""
    counts: Dict[str, int] = {}
    for state in (network or {}).values():
        cmp_group = (state or {}).get("CMP") or {}
        for v in cmp_group.get("vendors") or []:
            counts[v] = counts.get(v, 0) + int(cmp_group.get("count") or 1)
    return max(counts, key=counts.get) if counts else None


def banner_vendor(banner: dict, network: Optional[dict] = None) -> Optional[str]:
    """Which consent tool runs the banner: from its markup, then its servers, then the HTML. None if unknown."""
    probe = f"{banner.get('container') or ''} {banner.get('frame') or ''}".lower()
    return (next((n for key, n in _CMP_HINTS if key in probe), None)
            or _cmp_from_network(network)
            or banner.get("cmp_name"))


def _banner_description(banner: dict, network: Optional[dict] = None) -> str:
    """e.g. 'OneTrust · rendered in page'."""
    if not banner or not banner.get("detected"):
        return ""
    name = banner_vendor(banner, network) or "Custom banner"
    frame = banner.get("frame")
    where = ("in a CMP iframe" if frame and frame != "main"
             else "rendered in page" if banner.get("source") == "rendered" else "in page HTML")
    return f"{name} · {where}"


def _state(value: Optional[bool]) -> str:
    return "pass" if value is True else "fail" if value is False else "not_tested"


def _status_of(checks: Dict[str, Optional[bool]], required) -> str:
    vals = [checks.get(k) for k in required]
    if vals and all(v is True for v in vals):
        return "pass"
    if any(v is False for v in vals):
        return "fail"
    return "not_tested"


def _net_kind(category: str, entry: dict) -> str:
    if category in ("ANALYTICS", "ADVERTISING"):
        return "tracking" if entry.get("tracking_count") else "observation"
    if category in ("TAG_MANAGER", "SOCIAL"):
        return "observation"
    if category in ("CMP", "CONTENT_CDN", "FONT", "FIRST_PARTY"):
        return "infrastructure"
    return "other"


def _network_rows(summary: Optional[dict]) -> List[dict]:
    if not summary:
        return []
    rows = []
    for cat in _NET_ORDER + [k for k in summary if k not in _NET_ORDER]:
        e = summary.get(cat)
        if not e:
            continue
        kind = _net_kind(cat, e)
        note = {
            "tracking": f"{e.get('tracking_count', 0)} data-collection request(s) — tracking activity",
            "observation": ("Tag container loaded — not tracking by itself" if cat == "TAG_MANAGER"
                            else "Embed/widget loaded" if cat == "SOCIAL"
                            else "Library loaded, no data collection observed"),
            "infrastructure": "Infrastructure — not tracking",
            "other": "Not classified as tracking without further evidence",
        }[kind]
        rows.append({
            "category": cat,
            "label": e.get("label") or cat.replace("_", " ").title(),
            "count": e.get("count", 0),
            "tracking_count": e.get("tracking_count", 0),
            "vendors": e.get("vendors") or [],
            "samples": e.get("samples") or [],
            "tracking_samples": e.get("tracking_samples") or [],
            "kind": kind,
            "note": note,
        })
    return rows


def _before_consent_evidence(rows: List[dict]) -> tuple:
    """The real requests behind "Tracking before consent": collection hits and libraries that loaded. Returns (summary, items)."""
    items: List[dict] = []
    for r in rows:
        if not r.get("tracking_count"):
            continue
        tracked = r.get("tracking_samples")
        if tracked:
            for t in tracked:
                vendor, _, url = t.partition("|")
                items.append({"kind": "tracking", "vendor": vendor, "category": r.get("label"), "request": url})
        else:  # audits saved before tracking_samples existed
            vendors = ", ".join(r.get("vendors") or []) or r.get("label")
            for url in (r.get("samples") or [])[: r.get("tracking_count") or 1]:
                items.append({"kind": "tracking", "vendor": vendors, "category": r.get("label"), "request": url})
    for r in rows:
        if r.get("kind") != "observation":
            continue
        vendors = ", ".join(r.get("vendors") or []) or r.get("label")
        sample = (r.get("samples") or [None])[0]
        items.append({"kind": "observation", "vendor": vendors, "category": r.get("label"), "request": sample,
                      "note": r.get("note")})

    tracking = [i for i in items if i["kind"] == "tracking"]
    loaded = [i for i in items if i["kind"] == "observation"]
    parts = []
    if tracking:
        by_vendor: Dict[str, int] = {}
        for i in tracking:
            by_vendor[i["vendor"]] = by_vendor.get(i["vendor"], 0) + 1
        parts.append("Sent to " + ", ".join(f"{v} ({n})" if n > 1 else v for v, n in by_vendor.items()))
    if loaded:
        parts.append("Also loaded before consent: " + ", ".join(dict.fromkeys(i["vendor"] for i in loaded)))
    return " · ".join(parts), items


def build_consent_view(consent: Optional[dict]) -> Optional[dict]:
    if not consent:
        return None

    app: Dict[str, Any] = consent.get("applicability") or {}
    ts: Dict[str, Any] = consent.get("technical_scan") or {}
    rr: Dict[str, Any] = consent.get("runtime_result") or {}
    legacy = not app

    applicable = list(app.get("applicable_frameworks") or consent.get("applicable_frameworks") or [])
    region_label = app.get("region_label") or ("Unknown" if not legacy else "Not recorded")
    confidence = app.get("confidence") or consent.get("region_confidence") or ("low" if not legacy else None)
    assessed = bool(applicable) if not legacy else None
    scan = ts.get("scan") or {}

    # Laws
    frameworks: List[dict] = []
    fw_entries = {f.get("key"): f for f in (app.get("frameworks") or [])}
    for key, label in _FRAMEWORKS:
        is_applicable = (key in applicable) if not legacy else key in ("gdpr", "ccpa")
        entry: Dict[str, Any] = {"key": key, "label": label, "applicable": is_applicable,
                                 "reason": (fw_entries.get(key) or {}).get("reason", "")}
        if not is_applicable:
            entry.update(status="not_assessed", status_label="Not assessed", failed=[])
        else:
            if key == "gdpr":
                checks = consent.get("gdpr_checks") or {}
                status = _status_of(checks, _GDPR_REQUIRED) if checks else "not_tested"
                evidence = consent.get("gdpr_check_evidence") or {}
            elif key == "ccpa":
                checks = consent.get("ccpa_checks") or {}
                status = _status_of(checks, _CCPA_REQUIRED) if checks else "not_tested"
                evidence = {}
            else:
                a = (fw_entries.get("dpdp") or {}).get("assessment") or {}
                checks = a.get("checks") or {}
                status = a.get("status") or "not_tested"
                evidence = a.get("evidence") or {}
                labels = a.get("labels") or {}
            if key == "dpdp":
                lbl = lambda k: labels.get(k, k)  # noqa: E731
            else:
                lbl = lambda k: CHECK_LABELS.get(k, k)  # noqa: E731
            entry.update(
                status=status,
                status_label={"pass": "Passed", "fail": "Failed", "not_tested": "Not tested"}[status],
                checks=[{"key": k, "label": lbl(k), "state": _state(v)} for k, v in checks.items()],
                failed=[{"key": k, "label": lbl(k),
                         "reason": (evidence.get(k) or {}).get("reason", ""),
                         "items": (evidence.get(k) or {}).get("items", [])}
                        for k, v in checks.items() if v is False],
            )
        if legacy and is_applicable:
            entry["legacy"] = True
        frameworks.append(entry)

    # Buttons
    controls = ts.get("controls") or consent.get("consent_controls") or []
    controls = [{
        "label": c.get("label", ""),
        "action": c.get("action", ""),
        "action_label": c.get("action_label") or c.get("action", "").replace("_", " "),
        "evidence": c.get("evidence", ""),
        "layer": c.get("layer", 1),
    } for c in controls]
    # Only show buttons with a consent action; others (close, back...) are just counted.
    unclassified = [c for c in controls if (c["action"] or "unclassified") == "unclassified"]
    seen_controls = set()
    classified = []
    for c in controls:
        if (c["action"] or "unclassified") == "unclassified":
            continue
        key = (c["label"].strip().lower(), c["action"], c["layer"])
        if key in seen_controls:
            continue
        seen_controls.add(key)
        classified.append(c)
    controls = classified
    controls_hidden = {"count": len(unclassified),
                       "examples": list(dict.fromkeys(c["label"] for c in unclassified if c["label"]))[:6]}

    # Requests
    net = ts.get("network") or {}
    network = {
        state: _network_rows(net.get(state))
        for state in ("before_consent", "after_reject", "after_reject_next_page", "after_accept") if state in net
    }
    before_rows = network.get("before_consent") or []
    tracking_before = sum(r["tracking_count"] for r in before_rows)
    # Analytics/advertising requests include script and settings downloads; only some of them send data.
    tracking_rows_total = sum(r.get("count") or 0 for r in before_rows if r.get("category") in ("ANALYTICS", "ADVERTISING"))
    before_summary, before_items = _before_consent_evidence(before_rows)

    # Cookies
    ck = ts.get("cookies_before_consent") or {}
    cookies = [{"key": k, "label": label, "tone": tone, "count": len(ck.get(k) or []), "items": ck.get(k) or []}
               for k, label, tone in _COOKIE_GROUPS if ck.get(k)]

    # Headline tiles
    checks = ts.get("checks") or consent.get("gdpr_checks") or {}
    pref = ts.get("preferences") or {}
    tiles = [
        {"key": "banner", "label": "Consent banner",
         "value": "Detected" if consent.get("has_cookie_banner") else "Not detected",
         "sub": _banner_description(ts.get("banner") or {}, ts.get("network")),
         "state": "pass" if consent.get("has_cookie_banner") else "fail"},
        {"key": "region", "label": "Region",
         "value": region_label,
         "sub": (f"{confidence} confidence" if confidence else ""),
         "state": "info" if (assessed or legacy) else "neutral"},
        {"key": "tracking", "label": "Tracking before consent",
         "value": ("None observed" if checks.get("trackers_blocked_pre_consent") is True
                   else f"{tracking_before} data-collection request(s)" if checks.get("trackers_blocked_pre_consent") is False
                   else "Not tested"),
         # Same numbers as the "What loaded before the visitor chose" table: data-collection hits out of all requests.
         "sub": (f"{tracking_before} of the {tracking_rows_total} analytics/advertising requests sent data "
                 "(the others downloaded scripts or settings). "
                 if tracking_rows_total > tracking_before and checks.get("trackers_blocked_pre_consent") is False
                 else "") + (before_summary or ""),
         "details": before_items,
         "state": _state(checks.get("trackers_blocked_pre_consent"))},
        {"key": "reject", "label": "Reject works",
         "value": {True: "Blocks tracking", False: "Tracking continues", None: "Not tested"}[rr.get("reject_blocks_tracking")],
         "sub": (f"Clicked “{rr.get('reject_clicked_label')}”" if rr.get("reject_clicked_label") else ""),
         "state": _state(rr.get("reject_blocks_tracking"))},
        {"key": "accept", "label": "Accept works",
         "value": {True: "Enables tracking", False: "No tracking seen", None: "Not tested"}[rr.get("accept_allows_tracking")],
         "sub": (f"Clicked “{rr.get('accept_clicked_label')}”" if rr.get("accept_clicked_label") else ""),
         "state": {True: "pass", False: "info", None: "not_tested"}[rr.get("accept_allows_tracking")]},
        {"key": "preferences", "label": "Preferences panel",
         "value": {True: "Opens with choices", False: "Did not open", None: "Not tested"}[pref.get("panel_verified")],
         "sub": (f"{pref.get('panel_toggle_count')} category toggle(s)" if pref.get("panel_toggle_count") else ""),
         "state": _state(pref.get("panel_verified"))},
    ]

    screenshots = [{"key": key, "label": label, "url": consent.get(field), "captured": bool(consent.get(field))}
                   for key, label, field in _SCREENSHOT_SLOTS]

    return {
        "legacy": legacy,
        "status": {
            "banner_detected": bool(consent.get("has_cookie_banner")),
            "region": app.get("region") or consent.get("detected_region") or "UNKNOWN",
            "region_label": region_label,
            "confidence": confidence,
            "evidence": app.get("evidence") or consent.get("region_evidence") or [],
            "framework_label": app.get("framework_label") or ("Not determined" if not legacy else "GDPR + CCPA (legacy)"),
            "regional_compliance": ("assessed" if assessed else "not_assessed") if not legacy else "legacy",
            "regional_compliance_label": ("Assessed" if assessed else "Not assessed") if not legacy else "Legacy audit",
            "note": app.get("note") or "",
            "score": consent.get("consent_score"),
            "scan_id": scan.get("scan_id"),
            "scanned_at": scan.get("started_at"),
            "fresh_browser_contexts": scan.get("fresh_browser_contexts"),
            "banner_description": _banner_description(ts.get("banner") or {}, ts.get("network")),
            "banner_vendor": banner_vendor(ts.get("banner") or {}, ts.get("network")) if (ts.get("banner") or {}).get("detected") else None,
        },
        "tiles": tiles,
        "frameworks": frameworks,
        "controls": controls,
        "controls_hidden": controls_hidden,
        "network": network,
        "cookies": cookies,
        "screenshots": screenshots,
        "pipeline": scan.get("pipeline") or [],
        "legs": scan.get("legs") or [],
        "technical_checks": [{"key": k, "label": CHECK_LABELS.get(k, k), "state": _state(v),
                              "detail": (ts.get("check_details") or {}).get(k, "")}
                             for k, v in (ts.get("checks") or {}).items()],
    }


__all__ = ["build_consent_view", "CHECK_LABELS"]
