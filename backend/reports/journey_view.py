"""
reports/journey_view.py

One presentation model for the Customer Journey module, built from a stored
Journey row (dict), so the dashboard, report page, PDF, JSON export and
evidence ZIP all show the same journey evidence (same pattern as
reports/consent_view.py).

Report structure (requirement §15):
    Discovered Journey Paths · Interaction Details · Analytics Validation ·
    Journey Health (with what contributed to the score) · Findings ·
    Recommendations, plus Forms / Downloads / CTAs / Evidence.

Everything here is derived from the stored scan of THIS audit: journeys are
paths the crawler discovered between real pages and elements, not observed
visitor behaviour, and nothing is filled in from examples or defaults.

Analytics validation separates what was actually seen for an interaction:
an analytics request (network hit to GA4 / Adobe / Piano / Meta …), a
dataLayer push, both, a duplicate, nothing, or "unable to validate" (the
interaction was not executed, so tracking could not be checked).

Screenshot paths are stored relative to SCREENSHOT_DIR; here they become
the /screenshots/... URLs main.py serves.
"""

from __future__ import annotations

from typing import Dict, List, Optional

_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
_CONVERSION = {"cta", "form", "form_start", "download", "signup", "purchase", "appointment", "phone", "email", "login"}
# Journey goal types, as the interaction classifier names them.
_GOAL_LABELS = {"cta": "CTA", "form": "Lead form", "form_start": "Lead form", "download": "Download",
                "signup": "Signup", "purchase": "Purchase", "appointment": "Appointment", "phone": "Phone call",
                "email": "Email", "login": "Login"}
_IMPORTANCE = {3: "high", 2: "medium", 1: "low"}

ANALYTICS_LABELS = {
    "both": "Analytics hit + DataLayer event",
    "analytics_hit": "Analytics hit detected",
    "datalayer": "DataLayer event detected",
    "detected": "Tracking event detected",
    "duplicate": "Duplicate detected",
    "not_detected": "Not detected",
    "unable": "Unable to validate",
    "not_applicable": "—",
}
_TRACKED_RESULTS = {"both", "analytics_hit", "datalayer", "detected", "duplicate"}


def screenshot_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    path = str(path).replace("\\", "/")
    if path.startswith("/screenshots/"):
        return path
    marker = "/journey/"
    if marker in path and not path.startswith("journey/"):
        path = "journey/" + path.split(marker, 1)[1]
    return "/screenshots/" + path.lstrip("/")


def screenshot_file(url: Optional[str]) -> Optional[str]:
    """/screenshots/journey/... URL -> file path under SCREENSHOT_DIR (or None if missing)."""
    if not url or not url.startswith("/screenshots/"):
        return None
    from pathlib import Path

    from config.settings import settings

    base = Path(getattr(settings, "SCREENSHOT_DIR", "screenshots")).resolve()
    path = (base / url[len("/screenshots/"):]).resolve()
    if base not in path.parents or not path.is_file():
        return None
    return str(path)


def _shots(d: Optional[dict]) -> Dict[str, Optional[str]]:
    return {k: screenshot_url(v) for k, v in (d or {}).items() if v}


def _tracking_label(status: Optional[str]) -> str:
    return {"tracked": "Tracked", "not_tracked": "Not detected", "duplicate": "Duplicate event",
            "not_tested": "Not tested", "not_applicable": "—", None: "Not tested"}.get(status, status or "Not tested")


def _test_label(status: Optional[str]) -> str:
    return {"success": "Successfully tested", "failed": "Failed", "skipped": "Not executed (safety)",
            "not_tested": "Discovered (not tested)", "same_as_first": "Same as first occurrence",
            "consent_control": "Consent control (tested in Consent)"}.get(status or "", status or "")


def analytics_result(i: dict) -> dict:
    """What tracking was actually observed for one interaction."""
    tr = i.get("tracking") or {}
    st = tr.get("status")
    events = tr.get("events") or []
    net = any(e.get("source") == "network" for e in events)
    dl = any(e.get("source") == "dataLayer" for e in events)
    reason = ""
    if st in ("tracked", "duplicate"):
        base = "both" if (net and dl) else "analytics_hit" if net else "datalayer" if dl else "detected"
        key = "duplicate" if st == "duplicate" else base
    elif st == "not_tracked":
        key = "not_detected"
    elif st == "not_applicable":
        key = "not_applicable"
    else:
        key = "unable"
        test = i.get("status")
        reason = tr.get("note") or {
            "skipped": "The interaction was not executed (production safety), so tracking could not be checked.",
            "failed": "The interaction did not work, so no tracking could be expected.",
            "consent_control": "Cookie-banner control — validated by the Consent module.",
            "not_tested": "The interaction was discovered but not executed in this scan.",
        }.get(test or "", "Not executed in this scan.")
        if test == "failed":
            reason = "The interaction did not work, so no tracking could be expected."
    return {"key": key, "label": ANALYTICS_LABELS[key], "analytics_hit": net, "datalayer": dl,
            "duplicate": st == "duplicate", "reason": reason}


def safety_status(i: dict) -> dict:
    """Whether the interaction was executed, and if not, why."""
    st = i.get("status")
    if st == "skipped" or (st == "not_tested" and i.get("safe") is False):
        reason = i.get("unsafe_reason") or "potentially irreversible action"
        return {"key": "not_executed", "label": f"Not executed — {reason}"}
    if st == "consent_control":
        return {"key": "consent", "label": "Not executed here — cookie-banner control (tested by the Consent module)"}
    if st == "same_as_first":
        return {"key": "repeat", "label": "Same element as one tested on another page"}
    if st in ("success", "failed"):
        if i.get("outcome") == "external_link_checked":
            return {"key": "checked", "label": "External link — checked by HTTP request, not clicked"}
        return {"key": "executed", "label": "Executed in a real browser"}
    return {"key": "not_selected", "label": "Discovered — not selected for a live test (test limit or low-value element)"}


def _interaction_row(i: dict) -> dict:
    tr = i.get("tracking") or {}
    ar = analytics_result(i)
    sf = safety_status(i)
    return {
        "index": i.get("index"),
        "label": i.get("label"),
        "type": i.get("classification"),
        "type_label": i.get("classification_label"),
        "pattern": i.get("pattern"),
        "page": i.get("page_url"),
        "page_path": _path(i.get("page_url")),
        "destination": i.get("destination"),
        "test_status": i.get("status"),
        "test_label": _test_label(i.get("status")),
        "outcome": i.get("outcome"),
        "observed": i.get("observed"),
        "tracking_status": tr.get("status"),
        "tracking_label": _tracking_label(tr.get("status")),
        "tracking_events": [f"{e.get('vendor_label')}: {e.get('event')}" for e in (tr.get("events") or [])][:8],
        "tracking_note": tr.get("note"),
        "analytics_result": ar["key"],
        "analytics_label": ar["label"],
        "analytics_reason": ar["reason"],
        "analytics_hit": ar["analytics_hit"],
        "datalayer_event": ar["datalayer"],
        "safety_status": sf["key"],
        "safety_label": sf["label"],
        "importance": _IMPORTANCE.get(i.get("importance") or 1, "low"),
        "signals": i.get("signals") or [],
        "confidence": i.get("confidence"),
        "dynamic": i.get("dynamic"),
        "safe": i.get("safe"),
        "unsafe_reason": i.get("unsafe_reason"),
        "http_status": i.get("http_status"),
        "screenshots": _shots(i.get("screenshots")),
        "selector": i.get("selector"),
    }


def _path(url: Optional[str]) -> str:
    if not url:
        return ""
    from urllib.parse import urlparse

    p = urlparse(url)
    return (p.path or "/") + (("?" + p.query) if p.query else "")


def build_journey_view(journey: Optional[dict]) -> Optional[dict]:
    if not journey:
        return None
    health = journey.get("health") or {}
    counts = health.get("counts") or {}
    interactions = [i for i in (journey.get("interactions") or []) if i.get("duplicate_of") is None]
    rows = [_interaction_row(i) for i in interactions]
    by_index = {r["index"]: r for r in rows}
    jm = journey.get("journey_map") or {}
    nodes = jm.get("nodes") or {}

    # Map nodes with screenshot URLs.
    map_nodes = {}
    for nid, n in nodes.items():
        m = dict(n)
        if m.get("kind") == "page":
            m["screenshot"] = screenshot_url(m.get("screenshot"))
        else:
            m["screenshots"] = _shots(m.get("screenshots"))
            r = by_index.get(m.get("index"))
            if r:
                m.update({k: r[k] for k in ("analytics_result", "analytics_label", "safety_status",
                                            "safety_label", "importance")})
        map_nodes[nid] = m

    tested = [r for r in rows if r["test_status"] in ("success", "failed")]
    coverage_by_type: Dict[str, dict] = {}
    for r in tested:
        c = coverage_by_type.setdefault(r["type_label"], {
            "type": r["type_label"], "tested": 0, "tracked": 0, "analytics_hit": 0, "datalayer_only": 0,
            "both": 0, "not_tracked": 0, "duplicate": 0, "unable": 0})
        c["tested"] += 1
        a = r["analytics_result"]
        if a in _TRACKED_RESULTS:
            c["tracked"] += 1
            if r["analytics_hit"] and r["datalayer_event"]:
                c["both"] += 1
            elif r["analytics_hit"]:
                c["analytics_hit"] += 1
            elif r["datalayer_event"]:
                c["datalayer_only"] += 1
            if a == "duplicate":
                c["duplicate"] += 1
        elif a == "not_detected":
            c["not_tracked"] += 1
        else:
            c["unable"] += 1
    validation = {k: 0 for k in ("analytics_hit", "datalayer", "both", "not_detected", "duplicate", "unable")}
    for r in rows:
        a = r["analytics_result"]
        if a == "duplicate":
            validation["duplicate"] += 1
        if a in _TRACKED_RESULTS:
            if r["analytics_hit"] and r["datalayer_event"]:
                validation["both"] += 1
            elif r["analytics_hit"]:
                validation["analytics_hit"] += 1
            elif r["datalayer_event"]:
                validation["datalayer"] += 1
        elif a == "not_detected":
            validation["not_detected"] += 1
        elif a == "unable" and r["test_status"] not in ("consent_control",):
            validation["unable"] += 1

    gaps = [r for r in tested if r["test_status"] == "success" and r["tracking_status"] == "not_tracked"
            and r["type"] in _CONVERSION]

    findings = sorted(journey.get("findings") or [], key=lambda f: _SEVERITY_RANK.get(f.get("severity"), 3))
    recs: List[dict] = []
    seen = set()
    for f in findings:
        key = (f.get("category"), f.get("recommendation"))
        if key in seen:
            continue
        seen.add(key)
        recs.append({"severity": f.get("severity"), "title": f.get("title"),
                     "recommendation": f.get("recommendation")})

    gap_idx = {g["index"] for g in gaps}
    evidence = sorted([r for r in rows if r["screenshots"]], key=lambda r: (
        r["index"] not in gap_idx,                       # tracking gaps first
        r["test_status"] != "failed",                    # then failures
        r["type"] not in _CONVERSION,                    # then conversion interactions
        r["index"]))
    score = health.get("score")
    rates = health.get("rates") or {}
    critical = [f for f in findings if f.get("severity") == "critical"]
    conv_ok = [r for r in tested if r["test_status"] == "success" and r["type"] in _CONVERSION]
    conv_tracked = [r for r in conv_ok if r["analytics_result"] in _TRACKED_RESULTS]
    with_shot = [r for r in tested if (r["screenshots"] or {}).get("highlighted") or (r["screenshots"] or {}).get("before")]
    successful = [r for r in tested if r["test_status"] == "success"]

    def part(key, label, weight, rate, detail):
        return {"key": key, "label": label, "weight": weight, "rate": rate,
                "points": None if rate is None else round(weight * rate, 1), "detail": detail}

    breakdown = [] if score is None else [
        part("functional", "Functional success", 35, rates.get("success_rate"),
             f"{len(successful)} of {len(tested)} executed interactions worked."),
        part("tracking", "Tracking coverage", 45, rates.get("conversion_tracking_coverage"),
             (f"{len(conv_tracked)} of {len(conv_ok)} working conversion interactions (CTAs, forms, downloads, "
              "signups…) produced an analytics hit or dataLayer event.") if conv_ok else
             "No working conversion interaction was executed, so nothing could be missing (counted as full)."),
        part("evidence", "Evidence coverage", 20, rates.get("evidence_rate"),
             f"{len(with_shot)} of {len(tested)} executed interactions have a screenshot."),
    ]
    health_explained = {
        "formula": "35% functional success + 45% tracking coverage + 20% evidence coverage",
        "parts": breakdown,
        "critical_failures": len(critical),
        "critical_titles": [f.get("title") for f in critical[:5]],
    }

    # Discovered journey paths: enrich with type, importance and status from
    # the interactions themselves; most critical problems first.
    raw_by_index = {i.get("index"): i for i in interactions}
    journeys = []
    for j in jm.get("journeys") or []:
        goal_idx = None
        try:
            goal_idx = int(str(j.get("id", "")).split(":", 1)[1])
        except (IndexError, ValueError):
            pass
        goal = raw_by_index.get(goal_idx) or {}
        steps_int = [map_nodes.get(sid) for sid in j.get("steps") or [] if str(sid).startswith("int:")]
        steps_int = [n for n in steps_int if n]
        step_rows = [by_index.get(n.get("index")) for n in steps_int]
        step_rows = [r for r in step_rows if r]
        if any(r["test_status"] == "failed" for r in step_rows):
            status, status_label = "broken", "Broken step"
        elif j.get("tracking_gaps"):
            status, status_label = "tracking_gap", "Tracking gap"
        elif step_rows and all(r["analytics_result"] in _TRACKED_RESULTS for r in step_rows):
            status, status_label = "ok", "Working, tracking detected"
        else:
            status, status_label = "not_verified", "Not fully verified"
        imp = goal.get("importance") or 1
        journeys.append({
            **j,
            "goal_type_label": _GOAL_LABELS.get(j.get("goal_type"), goal.get("classification_label") or j.get("goal_type")),
            "importance": _IMPORTANCE.get(imp, "low"),
            "status": status,
            "status_label": status_label,
            "_rank": ({"broken": 0, "tracking_gap": 1, "not_verified": 2, "ok": 3}[status], -imp),
        })
    journeys.sort(key=lambda x: x["_rank"])
    for x in journeys:
        x.pop("_rank", None)

    tiles = [
        {"key": "pages", "label": "Pages scanned", "value": counts.get("pages_scanned", 0)},
        {"key": "journeys", "label": "Journey paths found", "value": len(journeys)},
        {"key": "interactions", "label": "Interactions found", "value": counts.get("interactions_discovered", 0)},
        {"key": "tested", "label": "Executed", "value": counts.get("interactions_tested", 0)},
        {"key": "successful", "label": "Worked", "value": counts.get("successful_interactions", 0)},
        {"key": "tracked", "label": "Tracking detected", "value": counts.get("tracked_interactions", 0)},
        {"key": "gaps", "label": "Tracking gaps", "value": counts.get("tracking_gaps", 0),
         "state": "fail" if counts.get("tracking_gaps") else "pass"},
        {"key": "skipped", "label": "Not executed (safety)",
         "value": len([r for r in rows if r["safety_status"] == "not_executed"])},
        {"key": "evidence", "label": "Evidence captured", "value": counts.get("evidence_captured", 0)},
    ]

    return {
        "available": bool(journey.get("available")),
        "error": journey.get("error"),
        "scan_id": journey.get("scan_id"),
        "consent_state": journey.get("consent_state"),
        "score": score,
        "rates": rates,
        "health_explained": health_explained,
        "provenance": ("These journey paths were discovered automatically from this scan of the website — its pages, "
                       "links, CTAs, forms and downloads, the interactions we executed and the tracking we observed. "
                       "They are not recordings of real visitors."),
        "counts": counts,
        "tiles": tiles,
        "by_type": [{"type": k, "count": v} for k, v in sorted((health.get("by_type") or {}).items(),
                                                                key=lambda kv: -kv[1])],
        "pages": [{**p, "screenshot": screenshot_url(p.get("screenshot"))} for p in (journey.get("pages") or [])],
        "interactions": rows,
        "map": {
            "start": jm.get("start"),
            "nodes": map_nodes,
            "edges": jm.get("edges") or [],
            "site_tree": jm.get("site_tree") or [],
            "journeys": journeys,
        },
        "tracking": {
            "vendors": (journey.get("tracking") or {}).get("vendors") or [],
            "analytics_present": (journey.get("tracking") or {}).get("analytics_present"),
            "coverage_by_type": list(coverage_by_type.values()),
            "validation": validation,
        },
        "gaps": gaps,
        "forms": journey.get("forms") or [],
        "downloads": [{**d, "screenshot": screenshot_url(d.get("screenshot")),
                       "row": by_index.get(d.get("index"))} for d in (journey.get("downloads") or [])],
        "ctas": [r for r in rows if r["type"] == "cta"],
        "evidence": evidence[:60],
        "findings": findings,
        "recommendations": recs[:20],
        "limits": journey.get("limits") or {},
        "started_at": journey.get("started_at"),
        "finished_at": journey.get("finished_at"),
    }


__all__ = ["build_journey_view", "screenshot_url", "screenshot_file"]
