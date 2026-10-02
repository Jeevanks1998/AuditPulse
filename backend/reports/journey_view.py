"""
reports/journey_view.py

One presentation model for the Customer Journey module, built from a stored
Journey row (dict), so the dashboard, report page, PDF, JSON export and
evidence ZIP all show the same journey evidence (same pattern as
reports/consent_view.py).

Report structure (requirement §15):
    Journey Health · Interaction Summary · Journey Map · Tracking Coverage ·
    Tracking Gaps · Forms · Downloads · CTAs · Evidence Screenshots ·
    Recommendations

Screenshot paths are stored relative to SCREENSHOT_DIR; here they become
the /screenshots/... URLs main.py serves.
"""

from __future__ import annotations

from typing import Dict, List, Optional

_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
_CONVERSION = {"cta", "form", "form_start", "download", "signup", "purchase", "appointment", "phone", "email", "login"}


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
            "not_tested": "Discovered (not tested)", "same_as_first": "Same as first occurrence"}.get(status or "", status or "")


def _interaction_row(i: dict) -> dict:
    tr = i.get("tracking") or {}
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
        map_nodes[nid] = m

    tested = [r for r in rows if r["test_status"] in ("success", "failed")]
    coverage_by_type: Dict[str, dict] = {}
    for r in tested:
        c = coverage_by_type.setdefault(r["type_label"], {"type": r["type_label"], "tested": 0, "tracked": 0,
                                                          "not_tracked": 0, "duplicate": 0})
        c["tested"] += 1
        st = r["tracking_status"]
        if st == "tracked":
            c["tracked"] += 1
        elif st == "duplicate":
            c["tracked"] += 1
            c["duplicate"] += 1
        elif st == "not_tracked":
            c["not_tracked"] += 1

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
    tiles = [
        {"key": "pages", "label": "Pages scanned", "value": counts.get("pages_scanned", 0)},
        {"key": "interactions", "label": "Interactions", "value": counts.get("interactions_discovered", 0)},
        {"key": "tested", "label": "Tested", "value": counts.get("interactions_tested", 0)},
        {"key": "successful", "label": "Successful", "value": counts.get("successful_interactions", 0)},
        {"key": "tracked", "label": "Tracked", "value": counts.get("tracked_interactions", 0)},
        {"key": "gaps", "label": "Tracking gaps", "value": counts.get("tracking_gaps", 0),
         "state": "fail" if counts.get("tracking_gaps") else "pass"},
        {"key": "forms", "label": "Forms", "value": counts.get("forms", 0)},
        {"key": "downloads", "label": "Downloads", "value": counts.get("downloads", 0)},
        {"key": "ctas", "label": "CTAs", "value": counts.get("ctas", 0)},
        {"key": "evidence", "label": "Evidence captured", "value": counts.get("evidence_captured", 0)},
    ]

    return {
        "available": bool(journey.get("available")),
        "error": journey.get("error"),
        "scan_id": journey.get("scan_id"),
        "consent_state": journey.get("consent_state"),
        "score": score,
        "rates": health.get("rates") or {},
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
            "journeys": jm.get("journeys") or [],
        },
        "tracking": {
            "vendors": (journey.get("tracking") or {}).get("vendors") or [],
            "analytics_present": (journey.get("tracking") or {}).get("analytics_present"),
            "coverage_by_type": list(coverage_by_type.values()),
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
