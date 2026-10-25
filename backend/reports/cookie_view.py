"""
Cookie Scanner: every cookie AuditPulse saw on the site, from what the audit
recorded in a real browser. Sources: the consent check (before consent,
after Reject, after Accept, then other pages after Accept), the Journey Map
pages, and the homepage's Set-Cookie headers.

Per cookie: name, domain, party, category, vendor, lifetime, security
flags, which states it appeared in, the page that set it, and any issues.
Cookie values are never stored or shown.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from cookies.categories import (
    ANALYTICS,
    CATEGORIES,
    CONSENT_MANAGEMENT,
    ESSENTIAL,
    FUNCTIONAL,
    MARKETING,
    UNKNOWN,
    classify_cookie,
    display_name,
    purpose_display_name,
    requires_consent,
)
from cookies.expiry import _CATEGORY_MAX_DAYS, _DEFAULT_MAX_DAYS

STATES = ("before_consent", "after_reject", "after_accept", "journey")
STATE_LABELS = {
    "before_consent": "Before consent",
    "after_reject": "After Reject",
    "after_accept": "After Accept",
    "journey": "Other pages (consent accepted)",
    "server": "Server response (homepage)",
}
CATEGORY_ORDER = (MARKETING, ANALYTICS, UNKNOWN, FUNCTIONAL, CONSENT_MANAGEMENT, ESSENTIAL)

# Labels that make a three-part main domain (axa.co.uk, example.com.au).
_SLD_SUFFIXES = {"co", "com", "org", "net", "gov", "ac", "edu", "ne", "or", "go", "gv"}


def site_domain(host: Optional[str]) -> str:
    """Main domain of a host: www.axa.ie -> axa.ie, shop.axa.co.uk -> axa.co.uk."""
    h = (host or "").lower().strip(".")
    parts = h.split(".")
    if len(parts) <= 2:
        return h
    if len(parts[-1]) == 2 and parts[-2] in _SLD_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _party(cookie_domain: str, site: str) -> str:
    d = (cookie_domain or "").lower().lstrip(".")
    if not d or not site:
        return "first"
    return "first" if (d == site or d.endswith("." + site)) else "third"


def _epoch(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (TypeError, ValueError):
        return None


def _lifetime_label(days: Optional[float], session: bool) -> str:
    if session:
        return "Session"
    if days is None:
        return "Not recorded"
    if days < 1:
        h = round(days * 24)
        return "Under 1 hour" if h < 1 else (f"{h} hour" if h == 1 else f"{h} hours")
    if days < 60:
        n = round(days)
        return f"{n} day" if n == 1 else f"{n} days"
    if days < 730:
        return f"{round(days / 30.4)} months"
    return f"{round(days / 365, 1):g} years"


def _norm_same_site(v) -> Optional[str]:
    if not v:
        return None
    v = str(v).strip().title()
    return v if v in ("Strict", "Lax", "None") else v


def _looks_like_session_id(name: str) -> bool:
    n = name.lower()
    if "csrf" in n or "xsrf" in n or "requestverificationtoken" in n:
        return False
    return any(t in n for t in ("session", "sessid", "auth", "token", "login"))


class _Entry:
    __slots__ = ("name", "domain", "path", "detail", "states", "pages", "first_state", "first_page", "order")

    def __init__(self, name, domain, path, order):
        self.name, self.domain, self.path = name, domain, path
        self.detail: Optional[dict] = None
        self.states: set = set()
        self.pages: List[str] = []
        self.first_state: Optional[str] = None
        self.first_page: Optional[str] = None
        self.order = order


def _detail_from(c: dict, observed_at: Optional[float]) -> Optional[dict]:
    """Expiry and flags from a stored cookie. None for older records without them."""
    if "secure" not in c:
        return None
    exp = c.get("expires")
    session = exp is None or exp == "session"
    days = None
    if not session:
        try:
            days = max(0.0, (float(exp) - (observed_at or time.time())) / 86400)
        except (TypeError, ValueError):
            days, session = None, False
    return {"session": session, "days": days, "expires": None if session else exp,
            "secure": bool(c.get("secure")), "http_only": bool(c.get("http_only")),
            "same_site": _norm_same_site(c.get("same_site")), "size": int(c.get("size") or 0)}


def build_cookie_inventory(consent: Optional[dict], journey: Optional[dict], url: str = "") -> dict:
    """Builds the Cookie Scanner view. Works with partial data."""
    host = urlparse(url or "").hostname or ""
    site = site_domain(host)
    entries: Dict[tuple, _Entry] = {}
    sources: List[str] = []
    notes: List[str] = []
    storage: Dict[str, dict] = {}

    def add(c: dict, state: str, page: Optional[str], observed_at: Optional[float]):
        name = c.get("name") or ""
        if not name:
            return
        domain = (c.get("domain") or host or "").lstrip(".").lower()
        path = c.get("path") or "/"
        key = (name, domain, path)
        e = entries.get(key)
        if e is None:
            e = entries[key] = _Entry(name, domain, path, len(entries))
            e.first_state, e.first_page = state, page
        e.states.add(state)
        if page and page not in e.pages:
            e.pages.append(page)
        if e.detail is None:
            e.detail = _detail_from(c, observed_at)

    # Consent check: the three states on the homepage
    rr = (consent or {}).get("runtime_result") or {}
    consent_observed = _epoch(rr.get("tested_at"))
    consent_ran = bool(rr.get("available"))
    tested_states = set()
    if consent_ran:
        sources.append("consent")
        for raw_state, state in (("before_consent", "before_consent"), ("after_reject", "after_reject"),
                                 ("after_reject_reload", "after_reject"), ("after_accept", "after_accept")):
            cap = rr.get(raw_state) or {}
            if not cap.get("available"):
                continue
            tested_states.add(state)
            page = cap.get("page_url") or url
            for c in cap.get("cookies") or []:
                add(c, state, page, consent_observed)
            for kind, keys in (("localStorage", cap.get("local_storage_keys")),
                               ("sessionStorage", cap.get("session_storage_keys"))):
                for k in keys or []:
                    s = storage.setdefault(f"{kind}|{k}", {"key": k, "type": kind, "states": []})
                    if state not in s["states"]:
                        s["states"].append(state)

    # Other pages visited after Accept
    site_pages = [p for p in (rr.get("site_pages") or []) if not p.get("error")] if consent_ran else []
    if site_pages:
        tested_states.add("journey")
        if "site" not in sources:
            sources.append("site")
        for p in site_pages:
            for c in p.get("cookies_set") or []:
                add(c, "journey", p.get("url"), consent_observed)

    # Journey Map: the page that first set each cookie
    j_pages = (journey or {}).get("pages") or []
    journey_observed = _epoch((journey or {}).get("started_at"))
    journey_pages_with_data = [p for p in j_pages if "cookies_set" in p]
    if journey_pages_with_data:
        sources.append("journey")
        tested_states.add("journey")
        for p in journey_pages_with_data:
            for c in p.get("cookies_set") or []:
                add(c, "journey", p.get("url"), journey_observed)
    elif j_pages:
        notes.append("This audit's Journey Map ran before page-by-page cookie capture was added. "
                     "Run the audit again to see which page sets each cookie.")

    # Server Set-Cookie headers on the homepage
    for c in (consent or {}).get("cookies_detected") or []:
        name = c.get("name")
        domain = (c.get("domain") or host or "").lstrip(".").lower()
        if not name or any(k[0] == name and k[1] == domain for k in entries):
            continue
        add({"name": name, "domain": domain}, "server", url, None)
        e = entries[(name, domain, "/")]
        exp = c.get("expires")
        if e.detail is None and exp is not None:
            e.detail = {"session": exp == "session", "days": None if exp == "session" else float(exp),
                        "expires": None, "secure": None, "http_only": None, "same_site": None, "size": 0}
        if "server" not in sources:
            sources.append("server")

    cookies = [_present(e, site, tested_states) for e in sorted(entries.values(), key=lambda e: e.order)]
    cookies.sort(key=lambda c: (0 if c["status"] == "issue" else 1 if c["status"] == "review" else 2,
                                CATEGORY_ORDER.index(c["category"]) if c["category"] in CATEGORY_ORDER else 9,
                                c["name"].lower()))

    by_cat = {cat: 0 for cat in CATEGORIES}
    for c in cookies:
        by_cat[c["category"]] = by_cat.get(c["category"], 0) + 1
    page_urls = {url.rstrip("/")} if consent_ran else set()
    page_urls |= {(p.get("url") or "").rstrip("/") for p in site_pages}
    page_urls |= {(p.get("url") or "").rstrip("/") for p in journey_pages_with_data}
    page_urls.discard("")
    pages_scanned = len(page_urls)

    if not consent_ran and not journey_pages_with_data:
        if (consent or {}).get("runtime_result") is not None or consent:
            notes.append("The live browser check could not run for this audit, so only cookies sent in the "
                         "homepage's server response are listed.")
    if consent_ran and not journey_pages_with_data and not site_pages:
        notes.append("Only the homepage was checked. Run the audit with \"Entire website\" to scan cookies "
                     "on the site's other pages too.")
    if any(c["detail_missing"] and c["first_seen_state"] != "server" for c in cookies):
        notes.append("Some cookies were recorded by an earlier version of AuditPulse without expiry and "
                     "security settings. Run the audit again for full detail.")

    summary = {
        "total": len(cookies),
        "first_party": sum(1 for c in cookies if c["party"] == "first"),
        "third_party": sum(1 for c in cookies if c["party"] == "third"),
        "by_category": by_cat,
        "consent_required": sum(1 for c in cookies if c["requires_consent"]),
        "before_consent_required": sum(1 for c in cookies if c["requires_consent"] and c["seen"]["before_consent"]),
        "after_reject_required": sum(1 for c in cookies if c["requires_consent"] and c["seen"]["after_reject"]),
        "with_issues": sum(1 for c in cookies if c["status"] == "issue"),
        "needs_review": sum(1 for c in cookies if c["status"] == "review"),
        "pages_scanned": pages_scanned,
        "storage_keys": len(storage),
    }
    available = bool(cookies) or consent_ran or bool(journey_pages_with_data)
    return {
        "available": available,
        "site": site or host,
        "sources": sources,
        "states_tested": [s for s in STATES if s in tested_states],
        "state_labels": STATE_LABELS,
        "summary": summary,
        "headline": _headline(summary, available, tested_states),
        "cookies": cookies,
        "storage": sorted(storage.values(), key=lambda s: (s["type"], s["key"].lower())),
        "notes": notes,
    }


def _present(e: _Entry, site: str, tested: set) -> dict:
    cls = classify_cookie(e.name, e.domain)
    party = _party(e.domain, site)
    d = e.detail or {}
    needs = requires_consent(cls.category)
    seen = {s: (s in e.states) if s in tested else None for s in STATES}
    if "server" in e.states and seen["before_consent"] is not True:
        seen["before_consent"] = True   # sent with the first response, before any choice

    days = d.get("days")
    session = bool(d.get("session"))
    cap = _CATEGORY_MAX_DAYS.get(cls.category, _DEFAULT_MAX_DAYS)
    too_long = bool(days is not None and cap is not None and days > cap)

    issues: List[str] = []
    if needs and seen["before_consent"]:
        issues.append("Set before the visitor gave consent")
    if needs and seen["after_reject"]:
        issues.append("Still present after the visitor clicked Reject")
    if too_long:
        issues.append(f"Lasts {_lifetime_label(days, False)}, longer than the ~{round(cap / 30.4)}-month "
                      f"guidance for {display_name(cls.category).lower()} cookies")
    if d.get("same_site") == "None" and d.get("secure") is False:
        issues.append("SameSite=None without Secure (browsers reject it)")
    if party == "third" and d.get("secure") is False:
        issues.append("Third-party cookie without Secure")
    # Only for login/session cookies: analytics cookies are set by JavaScript, so HttpOnly can't apply.
    if _looks_like_session_id(e.name) and d.get("http_only") is False and cls.category in (ESSENTIAL, UNKNOWN):
        issues.append("Looks like a session cookie but JavaScript can read it (no HttpOnly)")

    review = cls.category == UNKNOWN
    status = "issue" if issues else ("review" if review else "ok")
    expires_at = None
    if d.get("expires") not in (None, "session"):
        try:
            expires_at = datetime.fromtimestamp(float(d["expires"]), tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            expires_at = None

    return {
        "name": e.name,
        "domain": e.domain,
        "path": e.path,
        "party": party,
        "category": cls.category,
        "category_label": display_name(cls.category),
        "purpose": purpose_display_name(cls.purpose) if cls.purpose != "unknown" else None,
        "vendor": cls.vendor,
        "requires_consent": needs,
        "lifetime_days": round(days, 1) if days is not None else None,
        "lifetime_label": _lifetime_label(days, session) if e.detail else "Not recorded",
        "session": session,
        "expires_at": expires_at,
        "exceeds_retention": too_long,
        "secure": d.get("secure"),
        "http_only": d.get("http_only"),
        "same_site": d.get("same_site"),
        "size": d.get("size") or None,
        "seen": seen,
        "first_seen": STATE_LABELS.get(e.first_state, e.first_state),
        "first_seen_state": e.first_state,
        "set_by_page": e.first_page,
        "pages": e.pages[:25],
        "page_count": len(e.pages),
        "issues": issues,
        "status": status,
        "detail_missing": e.detail is None or d.get("secure") is None,
    }


def _headline(s: dict, available: bool, tested: set = frozenset()) -> str:
    if not available:
        return "No cookie data: the cookie scan did not run for this audit."
    if not s["total"]:
        return "No cookies were set on the pages checked."
    parts = [f"{s['total']} cookie{'s' if s['total'] != 1 else ''} found "
             f"({s['first_party']} first-party, {s['third_party']} third-party)"]
    if s["before_consent_required"]:
        parts.append(f"{s['before_consent_required']} analytics/marketing cookie"
                     f"{'s' if s['before_consent_required'] != 1 else ''} set before consent")
    if s["after_reject_required"]:
        parts.append(f"{s['after_reject_required']} still present after Reject")
    if "before_consent" not in tested and not s["before_consent_required"]:
        parts.append("consent states were not tested (Consent module not run)")
    elif not s["before_consent_required"] and not s["after_reject_required"]:
        parts.append("no analytics or marketing cookies before consent")
    return "; ".join(parts) + "."


def inventory_csv(inv: dict) -> str:
    """CSV of the inventory (same columns as the export button)."""
    import csv
    import io

    yes = {True: "Yes", False: "No", None: "Not tested"}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Domain", "Path", "Party", "Category", "Purpose", "Vendor", "Lifetime", "Expires",
                "Secure", "HttpOnly", "SameSite", "Before consent", "After Reject", "After Accept",
                "While browsing", "First seen", "Set by page", "Pages", "Status", "Issues"])
    for c in inv.get("cookies") or []:
        w.writerow([c["name"], c["domain"], c["path"], c["party"].title(), c["category_label"],
                    c["purpose"] or "", c["vendor"] or "", c["lifetime_label"], c["expires_at"] or "",
                    yes.get(c["secure"], ""), yes.get(c["http_only"], ""), c["same_site"] or "",
                    yes[c["seen"]["before_consent"]], yes[c["seen"]["after_reject"]],
                    yes[c["seen"]["after_accept"]], yes[c["seen"]["journey"]], c["first_seen"] or "",
                    c["set_by_page"] or "", c["page_count"], c["status"], " | ".join(c["issues"])])
    return buf.getvalue()


__all__ = ["build_cookie_inventory", "inventory_csv", "site_domain"]
