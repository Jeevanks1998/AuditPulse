"""
Live analytics check: opens the page in a real browser and confirms the
tracking actually works (finding the code is not proof).

Steps: load the page (page view), accept cookies, scroll, click a safe
element, then sort every captured request by tool and event and check for
double page views.

Never raises: on failure available=False. A tool that was never seen is
reported as failed (or "not tested" if the check didn't run), never as passed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from config.logging import logger
from crawler.screenshots import DEFAULT_VIEWPORT, NAVIGATION_TIMEOUT_MS
from config.browser import goto_page, launch_chromium

MODULE = "analytics"
CATEGORY = "runtime"

SETTLE_MS = 1_500
CONSENT_SETTLE_MS = 3_000  # tag managers load tools after the consent callback
# After consent, keep waiting while tracking requests keep arriving, up to this long.
CONSENT_SETTLE_MAX_MS = 9_000
QUIET_MS = 1_500
SCROLL_SETTLE_MS = 1_200
CLICK_SETTLE_MS = 1_500

# Never click consent buttons here; the Consent module tests those.
_CONSENT_LABEL_RE = re.compile(
    r"^\s*(accept|reject|allow|agree|decline|deny|disagree|manage|customi[sz]e|preferences|"
    r"cookie settings|settings)\b",
    re.IGNORECASE,
)

PASSED, FAILED, NOT_TESTED, NOT_APPLICABLE = "passed", "failed", "not_tested", "not_applicable"


@dataclass
class CapturedRequest:
    url: str
    phase: str  # "load" | "scroll" | "click"
    vendor_key: Optional[str] = None
    event_name: Optional[str] = None
    is_page_view: bool = False
    identifier: Optional[str] = None


# Request classifiers, one per tool: match the domain/path and read the event and ID.

def _ga4_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    # A GA4 hit is any /g/collect request with a G- ID (Google or a site's own server).
    tid = (qs.get("tid") or [""])[0]
    if urlparse(url).path.endswith("/g/collect") and tid.upper().startswith("G-"):
        event = (qs.get("en") or [None])[0]
        # stats.g.doubleclick.net/g/collect (Google signals) is sent together with a GA4 page view
        # whose own hit may go to a server-side endpoint the browser check can't name.
        signals = (urlparse(url).hostname or "").endswith("doubleclick.net") and event is None
        return CapturedRequest(url=url, phase="", vendor_key="ga4", event_name=event or ("page_view" if signals else None),
                               is_page_view=(event == "page_view") or signals, identifier=tid)
    if "google-analytics.com" not in url and "analytics.google.com" not in url:
        return None
    if "adblocker_check" in url and not tid:
        return None                      # gtag's ad-blocker probe, not a hit
    if "/g/collect" not in url and "/collect" not in url and "/j/collect" not in url:
        return None
    event = (qs.get("en") or [None])[0]
    return CapturedRequest(url=url, phase="", vendor_key="ga4", event_name=event,
                            is_page_view=(event == "page_view"), identifier=(qs.get("tid") or [None])[0])


def _gtm_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    if "googletagmanager.com" not in url:
        # Server-side GTM: <own domain>/gtm.js?id=GTM-XXXX
        cid = (qs.get("id") or [""])[0]
        if urlparse(url).path.endswith("/gtm.js") and cid.upper().startswith("GTM-"):
            return CapturedRequest(url=url, phase="", vendor_key="gtm", event_name="container_load",
                                   is_page_view=True, identifier=cid)
        return None
    # Only a real container load (/gtm.js) or its noscript fallback (/ns.html).
    # /gtag/js is gtag.js (GA4 installed directly), not GTM; see _gtag_classify.
    if "/gtm.js" not in url and "/ns.html" not in url:
        return None
    cid = (qs.get("id") or [None])[0]
    if cid and not cid.upper().startswith("GTM-"):
        return None  # not a GTM container ID
    # GTM's only own signal is the container loading; it counts as GTM's page view.
    return CapturedRequest(url=url, phase="", vendor_key="gtm", event_name="container_load",
                            is_page_view=True, identifier=cid)


def _gtag_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    """gtag.js (googletagmanager.com/gtag/js) installs GA4 or Google Ads without GTM.
    Only G- IDs are counted (as GA4); other uses are ignored.
    """
    if "googletagmanager.com" not in url or "/gtag/js" not in url:
        return None
    gid = (qs.get("id") or [None])[0]
    if not gid or not gid.upper().startswith("G-"):
        return None
    return CapturedRequest(url=url, phase="", vendor_key="ga4", event_name="gtag_script_load",
                            is_page_view=False, identifier=gid)


def _adobe_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    host = urlparse(url).hostname or ""
    if not host.endswith(".omtrdc.net"):
        return None
    pe = (qs.get("pe") or [None])[0]
    is_pv = pe is None or pe == "pv"  # s.t() page views have no `pe`; pe=lnk_o is a link click
    event_name = "page_view" if is_pv else ("click" if pe == "lnk_o" else pe)
    return CapturedRequest(url=url, phase="", vendor_key="adobe", event_name=event_name,
                            is_page_view=is_pv, identifier=(qs.get("s_account") or qs.get("account") or [None])[0])


def _piano_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    host = urlparse(url).hostname or ""
    # pa-cd.com is Piano's current domain; xiti.com / aticdn.net are older.
    path = urlparse(url).path or ""
    known_host = any(d in host for d in ("aticdn.net", "piano.io", "xiti.com", "pa-cd.com"))
    # Piano on a site's own domain: /event + numeric site id + idclient.
    first_party = (path.endswith("/event") or path.endswith("/hit.xiti")) \
        and (qs.get("s") or [""])[0].isdigit() and ("idclient" in qs or "idclient" in url)
    if not (known_host or first_party):
        return None
    if path.endswith(".js"):
        return None                      # the SDK file itself is not a hit
    if "event" not in url and "hit" not in url and "collect" not in url:
        return None
    raw = (qs.get("events") or qs.get("event") or [None])[0]
    event = raw
    if raw and raw.lstrip().startswith("["):
        # Piano sends events=[{"name":"page.display",...}]
        try:
            import json as _json
            parsed = _json.loads(raw)
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                event = parsed[0].get("name") or raw
        except ValueError:
            event = raw
    # Old AT Internet hits without an event are page views; Piano calls it "page.display".
    is_pv = event is None or event == "page.display"
    return CapturedRequest(url=url, phase="", vendor_key="piano", event_name=event or "page_view",
                            is_page_view=is_pv, identifier=(qs.get("s") or qs.get("site") or [None])[0])


def _clarity_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    if "clarity.ms" not in url or "/collect" not in url:
        return None
    return CapturedRequest(url=url, phase="", vendor_key="clarity", event_name="session_event", is_page_view=False)


def _hotjar_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    if "hotjar.com" not in url:
        return None
    return CapturedRequest(url=url, phase="", vendor_key="hotjar", event_name="activity", is_page_view=False)


def _meta_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    if "facebook.com/tr" not in url and "facebook.net" not in url:
        return None
    if "/tr" not in url:
        return None
    ev = (qs.get("ev") or [None])[0]
    return CapturedRequest(url=url, phase="", vendor_key="meta_pixel", event_name=ev,
                            is_page_view=(ev == "PageView"), identifier=(qs.get("id") or [None])[0])


def _linkedin_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    if "px.ads.linkedin.com" not in url or "/collect" not in url:
        return None
    return CapturedRequest(url=url, phase="", vendor_key="linkedin", event_name="page_view", is_page_view=True,
                            identifier=(qs.get("pid") or [None])[0])


def _tiktok_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    if "analytics.tiktok.com" not in url:
        return None
    if "/pixel" not in url and "/api/v2" not in url:
        return None
    return CapturedRequest(url=url, phase="", vendor_key="tiktok", event_name="page_view", is_page_view=True)


def _has_duplicate_page_view(vendor_key: str, page_views: List[CapturedRequest]) -> bool:
    """More than one Page View to the same property/ID on one load. TagCommander containers are not page views of their own."""
    if vendor_key in ("tagcommander", "gtm") or len(page_views) < 2:
        return False
    per_id: Dict[str, int] = {}
    for r in page_views:
        key = r.identifier or ""
        per_id[key] = per_id.get(key, 0) + 1
    return any(n > 1 for n in per_id.values())



def _sent_by_gtm(url: str) -> bool:
    """A hit sent by a tag inside a Google Tag Manager container (gtm= on Google hits, GTM templates on others)."""
    q = parse_qs(urlparse(url).query)
    if (q.get("gtm") or [""])[0]:
        return True
    return "-gtm-" in url.lower() or "gtm-webtemplate" in url.lower()


def _tagcommander_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    """TagCommander container (cdn.tagcommander.com/.../tc_Name_n.js or *.commander1.com). Its own signal is the container load."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if not (host.endswith("tagcommander.com") or host.endswith("commander1.com")):
        return None
    if not p.path.endswith(".js"):
        return None
    m = re.search(r"tc_([A-Za-z0-9]+)_\d+\.js$", p.path)
    return CapturedRequest(url=url, phase="", vendor_key="tagcommander", event_name="container_load",
                           is_page_view=True, identifier=m.group(1) if m else None)


_CLASSIFIERS = [
    _ga4_classify, _gtm_classify, _gtag_classify, _tagcommander_classify, _adobe_classify, _piano_classify,
    _clarity_classify, _hotjar_classify, _meta_classify, _linkedin_classify, _tiktok_classify,
]

VENDOR_LABELS = {
    "ga4": "Google Analytics 4",
    "gtm": "Google Tag Manager",
    "tagcommander": "TagCommander",
    "adobe": "Adobe Analytics",
    "piano": "Piano Analytics",
    "clarity": "Microsoft Clarity",
    "hotjar": "Hotjar",
    "meta_pixel": "Meta Pixel",
    "linkedin": "LinkedIn Insight Tag",
    "tiktok": "TikTok Pixel",
}


def _classify(url: str) -> Optional[CapturedRequest]:
    try:
        qs = parse_qs(urlparse(url).query)
    except Exception:  # noqa: BLE001
        qs = {}
    for fn in _CLASSIFIERS:
        match = fn(url, qs)
        if match is not None:
            return match
    return None


@dataclass
class VendorRuntimeResult:
    vendor_key: str
    vendor_name: str
    detected: bool = False
    runtime_tested: bool = False
    identifier: Optional[str] = None
    page_view_status: str = NOT_TESTED
    scroll_status: str = NOT_APPLICABLE
    click_status: str = NOT_APPLICABLE
    custom_event_status: str = NOT_APPLICABLE
    duplicate_page_view: bool = False
    captured_request_count: int = 0
    request_urls: List[str] = field(default_factory=list)
    event_names: List[str] = field(default_factory=list)


@dataclass
class AnalyticsRuntimeResult:
    available: bool = False
    error: Optional[str] = None
    vendors: Dict[str, VendorRuntimeResult] = field(default_factory=dict)
    clicked_element: Optional[str] = None
    tested_at: Optional[str] = None
    # Did the scroll/click step actually run? If not, report "not tested", not "failed".
    scroll_tested: bool = False
    click_tested: bool = False
    # What happened to the cookie banner, e.g. "no_banner" or "accepted (<label>)".
    consent_state: Optional[str] = None
    # Small JS-global evidence read from the rendered page (dataLayer,
    # tag-manager objects). Kept tiny: this whole dataclass is stored as JSON.
    page_globals: Dict[str, object] = field(default_factory=dict)
    # Every tracking service seen loading in the browser: {vendor, category, requests, collection_requests, hosts, phases}.
    observed_tags: List[dict] = field(default_factory=list)


# Read after load. Counts and flags only, never page content.
_PAGE_GLOBALS_JS = r"""() => ({
  dataLayer: Array.isArray(window.dataLayer) ? window.dataLayer.length : null,
  // Entries that are not the cookie banner's own consent bookkeeping
  // (OneTrustLoaded, OptanonLoaded, cookie_consent_update, gtag('consent', …)).
  dataLayer_meaningful: Array.isArray(window.dataLayer) ? window.dataLayer.filter(e => {
    try {
      if (e && typeof e === 'object' && e.length !== undefined && e[0] === 'consent') return false;
      const ev = e && typeof e.event === 'string' ? e.event : '';
      if (/onetrust|optanon|cookiebot|didomi|usercentrics|axeptio|tc_privacy|consent|cmp/i.test(ev)) return false;
      if (ev === '' && e && typeof e === 'object' && Object.keys(e).every(k => /onetrust|optanon|consent|cmp/i.test(k))) return false;
      return true;
    } catch (x) { return true; }
  }).length : null,
  google_tag_manager: !!window.google_tag_manager,
  gtag: typeof window.gtag === 'function',
  // TagCommander = a Commanders Act *tag container* (tC.container_<site>_<n>
  // or a tc_<Name>_<n>.js script). window.tC alone is not enough: the
  // TrustCommander cookie banner creates it too.
  tagcommander: (() => { try {
    const srcs = Array.from(document.scripts).map(s => s.src || '');
    if (srcs.some(s => /tagcommander\.com\/\d+\/|\/tc_[\w-]+_\d+\.js/i.test(s))) return true;
    return !!window.tC && Object.keys(window.tC).some(k => /^container_\d+_\d+$/.test(k));
  } catch (e) { return false; } })(),
  tagcommander_containers: (() => { try {
    return Array.from(new Set(Array.from(document.scripts).map(s => (/\/tc_([\w-]+)_\d+\.js/i.exec(s.src || '') || [])[1]).filter(Boolean))).slice(0, 10);
  } catch (e) { return []; } })(),
  // IDs the page's own tracking libraries have loaded (tags added by GTM or
  // after consent never appear in the HTML).
  google_tag_ids: (() => { try {
    return Object.keys(window.google_tag_manager || {}).filter(k => /^(G|GTM|AW|DC|GT)-[A-Z0-9]+$/.test(k)).slice(0, 20);
  } catch (e) { return []; } })(),
  meta_pixel_ids: (() => { try {
    return Object.keys((window.fbq && window.fbq.instance && window.fbq.instance.pixelsByID) || {}).slice(0, 10);
  } catch (e) { return []; } })(),
  linkedin_partner_ids: (() => { try {
    return (window._linkedin_data_partner_ids || []).concat(window._linkedin_partner_id ? [window._linkedin_partner_id] : []).map(String).slice(0, 10);
  } catch (e) { return []; } })(),
  tealium: !!window.utag,
  adobe_launch: !!window._satellite,
  piano: !!(window.pa || window.ATInternet || window._pac),
  piano_site: (() => { try { return window.pa && window.pa.getConfiguration ? String(window.pa.getConfiguration('site') || '') || null : null; } catch (e) { return null; } })(),
  piano_collect_domain: (() => { try { return window.pa && window.pa.getConfiguration ? String(window.pa.getConfiguration('collectDomain') || '') || null : null; } catch (e) { return null; } })(),
  matomo: Array.isArray(window._paq),
  scripts: Array.from(document.scripts).map(s => s.src).filter(Boolean).length
})"""


def _now() -> float:
    import time
    return time.monotonic()


async def _settle_after_consent(page, activity: dict) -> None:
    """Wait, then keep waiting while tracking requests arrive (up to CONSENT_SETTLE_MAX_MS)."""
    start = _now()
    await page.wait_for_timeout(CONSENT_SETTLE_MS)
    while (_now() - start) * 1000 < CONSENT_SETTLE_MAX_MS and (_now() - activity["last"]) * 1000 < QUIET_MS:
        await page.wait_for_timeout(500)


async def _accept_consent(page) -> str:
    """Clicks the banner's Accept button."""
    try:
        from consent.buttons import ACCEPT_CLICK_ORDER
        from consent.runtime import _click_control, inventory_banner

        # Wait for a late banner (e.g. OneTrust on slow pages); otherwise consent-gated tags never fire.
        try:
            from consent.runtime import _wait_for_banner
            inv, handles = await _wait_for_banner(page)
        except ImportError:
            inv, handles = await inventory_banner(page)
        if not inv.banner_detected:
            return "no_banner"
        accept = inv.first(ACCEPT_CLICK_ORDER)
        if accept is None:
            return "banner_without_accept"
        ok = await _click_control(page, handles, accept)
        return f"accepted ({accept.label})" if ok else "accept_click_failed"
    except Exception as exc:  # noqa: BLE001 — consent handling must never break the analytics pass
        return f"not_handled ({str(exc)[:80]})"


async def run_analytics_runtime(url: str) -> AnalyticsRuntimeResult:
    """Runs the live check, retrying once in a fresh browser if the page didn't load."""
    import asyncio

    result = await _run_analytics_runtime_once(url)
    if not result.available:
        logger.warning(f"analytics/runtime.py: retrying runtime validation for {url} ({result.error})")
        await asyncio.sleep(3)
        result = await _run_analytics_runtime_once(url)
    return result


async def _run_analytics_runtime_once(url: str) -> AnalyticsRuntimeResult:
    """One live check of `url`: page view on load, scroll, then a safe click."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("analytics/runtime.py: playwright not installed — skipping analytics runtime validation")
        return AnalyticsRuntimeResult(available=False, error="playwright not installed")

    captured: List[CapturedRequest] = []
    phase = {"current": "load"}
    observed: Dict[str, dict] = {}
    site_host = urlparse(url).hostname or ""

    activity = {"last": 0.0}

    def _on_request(request):
        match = _classify(request.url)
        if match is not None:
            match.phase = phase["current"]
            captured.append(match)
            activity["last"] = _now()
        _observe(request)

    def _observe(request):
        try:
            from consent.network import ADVERTISING, ANALYTICS, COLLECTION, TAG_MANAGER, classify_request
            nr = classify_request(request.url, request.resource_type, site_host)
        except Exception:  # noqa: BLE001 — evidence collection must never break the pass
            return
        if nr.category not in (ANALYTICS, ADVERTISING, TAG_MANAGER) or not nr.vendor:
            return
        activity["last"] = _now()
        o = observed.setdefault(nr.vendor, {"vendor": nr.vendor, "category": nr.category, "requests": 0,
                                            "collection_requests": 0, "hosts": [], "phases": []})
        o["requests"] += 1
        if nr.activity == COLLECTION:
            o["collection_requests"] += 1
        if nr.domain and nr.domain not in o["hosts"] and len(o["hosts"]) < 4:
            o["hosts"].append(nr.domain)
        if phase["current"] not in o["phases"]:
            o["phases"].append(phase["current"])

    # available becomes True only once the page loads; otherwise every tool is "not tested".
    result = AnalyticsRuntimeResult(available=False, tested_at=datetime.now(timezone.utc).isoformat())

    try:
        async with async_playwright() as pw:
            browser = await launch_chromium(pw)
            try:
                context = await browser.new_context(viewport=DEFAULT_VIEWPORT)
                page = await context.new_page()
                page.on("request", _on_request)

                # Load / page view
                await goto_page(page, url, timeout=max(NAVIGATION_TIMEOUT_MS, 30_000))
                await page.wait_for_timeout(SETTLE_MS)
                result.available = True

                # Consent (hits right after Accept still count as the page view)
                result.consent_state = await _accept_consent(page)
                if result.consent_state.startswith("accepted"):
                    await _settle_after_consent(page, activity)

                # Rendered page: JavaScript-added tags aren't in the raw HTML, so the
                # static detectors re-run on this DOM. Returned to the caller, not saved.
                try:
                    result.page_globals = await page.evaluate(_PAGE_GLOBALS_JS)
                except Exception:  # noqa: BLE001
                    result.page_globals = {}
                try:
                    result._rendered_html = await page.content()
                except Exception:  # noqa: BLE001
                    result._rendered_html = None

                # Scroll (its own try, so a failure here keeps the page-view evidence)
                phase["current"] = "scroll"
                try:
                    try:
                        await page.mouse.wheel(0, 2500)
                        await page.wait_for_timeout(400)
                        await page.mouse.wheel(0, 2500)
                    except Exception:  # noqa: BLE001 — a page with no scrollable content shouldn't abort the pass
                        pass
                    await page.wait_for_timeout(SCROLL_SETTLE_MS)
                    result.scroll_tested = True
                except Exception as exc:  # noqa: BLE001
                    logger.info(f"analytics/runtime.py: scroll phase failed for {url}: {exc}")

                # Look again: late tags (after consent or scroll) are in the page now.
                try:
                    late = await page.evaluate(_PAGE_GLOBALS_JS)
                    for k, v in (late or {}).items():
                        if v and not result.page_globals.get(k):
                            result.page_globals[k] = v
                    result._rendered_html = await page.content()
                except Exception:  # noqa: BLE001 — keep the first snapshot
                    pass

                # Click. No safe element to click means "not tested", not broken tracking.
                phase["current"] = "click"
                try:
                    clicked = await _click_safe_element(page)
                    result.clicked_element = clicked
                    result.click_tested = clicked is not None
                    if result.click_tested:
                        await page.wait_for_timeout(CLICK_SETTLE_MS)
                except Exception as exc:  # noqa: BLE001
                    logger.info(f"analytics/runtime.py: click phase failed for {url}: {exc}")
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 — a failed runtime pass should never break the audit
        logger.warning(f"analytics/runtime.py: runtime validation failed for {url}: {exc}")
        result.error = str(exc)

    result.vendors = _build_vendor_results(
        captured, scroll_tested=result.scroll_tested, click_tested=result.click_tested,
    )
    order = {"TAG_MANAGER": 0, "ANALYTICS": 1, "ADVERTISING": 2}
    result.observed_tags = sorted(observed.values(),
                                  key=lambda o: (order.get(o["category"], 9), -o["requests"]))[:40]
    return result


async def _click_safe_element(page) -> Optional[str]:
    """Clicks the first visible non-consent <button> or in-page link. Returns what was clicked, or None."""
    candidates = page.locator("button, a[href^='#']")
    try:
        count = await candidates.count()
    except Exception:  # noqa: BLE001
        return None

    for i in range(min(count, 100)):
        el = candidates.nth(i)
        try:
            if not await el.is_visible():
                continue
            text = (await el.inner_text()).strip()
            if text and _CONSENT_LABEL_RE.match(text):
                continue
            await el.click(timeout=3_000)
            return text or "(unlabeled element)"
        except Exception:  # noqa: BLE001
            continue
    return None


# Session-recording tools send session data, never a "page view" hit: data sent on load counts as recording the visit.
SESSION_VENDORS = frozenset({"clarity", "hotjar"})


def _build_vendor_results(
    captured: List[CapturedRequest], scroll_tested: bool = True, click_tested: bool = True,
) -> Dict[str, VendorRuntimeResult]:
    """Builds per-tool results. A step that didn't run is reported "not tested", not "failed"."""
    by_vendor: Dict[str, List[CapturedRequest]] = {}
    for req in captured:
        by_vendor.setdefault(req.vendor_key, []).append(req)

    results: Dict[str, VendorRuntimeResult] = {}
    for vendor_key, requests in by_vendor.items():
        load_reqs = [r for r in requests if r.phase == "load"]
        scroll_reqs = [r for r in requests if r.phase == "scroll"]
        click_reqs = [r for r in requests if r.phase == "click"]

        page_views_on_load = [r for r in load_reqs if r.is_page_view]
        if vendor_key in SESSION_VENDORS:
            page_views_on_load = load_reqs[:1]
        # Tags released by the consent tool can fire a little later (during the scroll step):
        # that is still the page view of this page load, not "no page view".
        late_page_views = [r for r in scroll_reqs if r.is_page_view] if not page_views_on_load else []
        if vendor_key in SESSION_VENDORS and not page_views_on_load:
            late_page_views = scroll_reqs[:1]
        identifier = next((r.identifier for r in requests if r.identifier), None)

        # GTM and TagCommander send no scroll/click hits of their own: "not applicable".
        if vendor_key in ("gtm", "tagcommander"):
            scroll_status = NOT_APPLICABLE
            click_status = NOT_APPLICABLE
        else:
            scroll_status = NOT_TESTED if not scroll_tested else (PASSED if scroll_reqs else FAILED)
            click_status = NOT_TESTED if not click_tested else (PASSED if click_reqs else FAILED)

        vendor = VendorRuntimeResult(
            vendor_key=vendor_key,
            vendor_name=VENDOR_LABELS.get(vendor_key, vendor_key),
            detected=True,
            runtime_tested=True,
            identifier=identifier,
            page_view_status=PASSED if (page_views_on_load or late_page_views) else FAILED,
            scroll_status=scroll_status,
            click_status=click_status,
            custom_event_status=PASSED if any(
                r.event_name and not r.is_page_view for r in requests
            ) else NOT_APPLICABLE,
            # Per property: one Page View to each of two GA4 properties (dual tagging) is not a duplicate.
            duplicate_page_view=_has_duplicate_page_view(vendor_key, page_views_on_load),
            captured_request_count=len(requests),
            request_urls=[r.url for r in requests][:25],  # capped
            event_names=sorted({r.event_name for r in requests if r.event_name}),
        )
        results[vendor_key] = vendor

    if "gtm" not in results:
        fired_by_gtm = [r for r in captured if r.vendor_key != "gtm" and _sent_by_gtm(r.url)]
        if fired_by_gtm:
            results["gtm"] = VendorRuntimeResult(
                vendor_key="gtm", vendor_name=VENDOR_LABELS.get("gtm", "Google Tag Manager"), detected=True,
                runtime_tested=True, identifier=None, page_view_status=PASSED,
                scroll_status=NOT_APPLICABLE, click_status=NOT_APPLICABLE, custom_event_status=NOT_APPLICABLE,
                duplicate_page_view=False, captured_request_count=0,
                request_urls=[r.url for r in fired_by_gtm][:5],
                event_names=["container_ran (tags it fired were seen)"],
            )

    return results


def check_runtime_analytics(
    result: AnalyticsRuntimeResult,
    page_url: str,
    static_detected: Optional[Dict[str, bool]] = None,
) -> List[dict]:
    """Findings from the live check, including tags in the code that never fire. [] if it didn't run."""
    if not result.available:
        return []

    findings: List[dict] = []
    static_detected = static_detected or {}

    for vendor_key, static_present in static_detected.items():
        if not static_present:
            continue
        vendor = result.vendors.get(vendor_key)
        label = VENDOR_LABELS.get(vendor_key, vendor_key)
        if vendor is not None and vendor.captured_request_count and vendor.page_view_status != PASSED:
            # It does send data (e.g. on scroll or click), just no page view: never call that "never fires".
            findings.append(_finding(
                "warning",
                f"{label} sends data but no page view was recorded on load",
                f"{page_url}: {label} sent {vendor.captured_request_count} request(s) during the live check, "
                "but none of them was a page view when the page loaded.",
                f"Check the {label} page-view trigger: it should fire once on every page load.",
            ))
            continue
        if vendor is None or vendor.page_view_status != PASSED:
            findings.append(_finding(
                "critical",
                f"{label} is detected in code but never fires at runtime",
                f"{page_url}: {label} was found in the page's markup, but no Page View request "
                "was observed in a live browser session — the implementation is present but not working.",
                f"Open the browser network tab on {page_url} and confirm a {label} request actually "
                "fires on load; check for JS errors, ad blockers in your test environment, or a "
                "misconfigured tag trigger.",
            ))

    for vendor_key, vendor in result.vendors.items():
        label = vendor.vendor_name
        if vendor.duplicate_page_view:
            findings.append(_finding(
                "warning",
                f"{label} sends duplicate Page View requests",
                f"{page_url}: more than one Page View request was observed for {label} on a single "
                "page load, which will inflate pageview counts in reporting.",
                "Check for the tag being installed twice (e.g. both hardcoded and via GTM) "
                "or fired from more than one trigger.",
            ))
        if vendor.scroll_status == FAILED:
            findings.append(_finding(
                "info",
                f"{label} did not send a request during scroll testing",
                f"{page_url}: no {label} request was observed while scrolling the page. This is "
                "expected if no scroll-tracking event is configured, otherwise it may indicate "
                "a broken scroll trigger.",
                "Confirm whether scroll tracking is expected for this implementation.",
            ))

    return findings


def merge_static_detected_vendors(
    result: AnalyticsRuntimeResult,
    static_detected: Dict[str, bool],
) -> None:
    """Adds a row for every tool found in the code but not seen in the browser,
    so the report never drops it:
      - check didn't run: statuses stay "not tested"
      - check ran, tool never seen: page view "failed"; scroll/click "failed"
        only if that step ran
    Existing rows (real browser evidence) are never overwritten.
    """
    for vendor_key, detected in (static_detected or {}).items():
        if not detected or vendor_key in result.vendors:
            continue
        label = VENDOR_LABELS.get(vendor_key, vendor_key)
        if result.available:
            page_view_status = FAILED
            scroll_status = FAILED if result.scroll_tested else NOT_TESTED
            click_status = FAILED if result.click_tested else NOT_TESTED
        else:
            page_view_status = NOT_TESTED
            scroll_status = NOT_APPLICABLE
            click_status = NOT_APPLICABLE
        result.vendors[vendor_key] = VendorRuntimeResult(
            vendor_key=vendor_key,
            vendor_name=label,
            detected=True,
            runtime_tested=result.available,
            page_view_status=page_view_status,
            scroll_status=scroll_status,
            click_status=click_status,
            custom_event_status=NOT_APPLICABLE,
        )


def _finding(severity: str, title: str, description: str, recommendation: str) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }


# Shared helpers also used by journey/ (one browser implementation):
#   open_runtime_browser()       - Chromium launch
#   classify_analytics_request() - same classifiers, plus batched GA4 POST bodies
#   DATALAYER_HOOK_JS            - reports every dataLayer.push / gtag() call

import contextlib  # noqa: E402

DATALAYER_BINDING = "__auditpulseDataLayer"

DATALAYER_HOOK_JS = r"""
(() => {
  const report = (payload) => {
    try { window.%(binding)s && window.%(binding)s(JSON.stringify(payload)); } catch (e) {}
  };
  const wrap = (arr) => {
    if (!arr || arr.__apWrapped) return arr;
    const orig = arr.push.bind(arr);
    arr.push = function (...items) {
      for (const it of items) {
        let ev = null, params = {};
        try {
          const isArgs = Object.prototype.toString.call(it) === '[object Arguments]' || Array.isArray(it);
          if (it && typeof it === 'object' && !isArgs) {
            ev = it.event || null; params = it;
          } else if (it && isArgs) {                            // gtag('event', name, params) -> arguments object
            if (it[0] === 'event') { ev = it[1]; params = it[2] || {}; }
            else { ev = 'gtag:' + it[0]; params = { arg: it[1] }; }
          }
        } catch (e) {}
        let safe = {};
        try { safe = JSON.parse(JSON.stringify(params, (k, v) => (typeof v === 'function' || (v && v.nodeType)) ? undefined : v)); } catch (e) {}
        report({ source: 'dataLayer', event: ev, params: safe, ts: Date.now(), url: location.href });
      }
      return orig(...items);
    };
    arr.__apWrapped = true;
    return arr;
  };
  let current = wrap(window.dataLayer || []);
  try {
    Object.defineProperty(window, 'dataLayer', {
      configurable: true,
      get() { return current; },
      set(v) { current = wrap(v); },
    });
  } catch (e) { window.dataLayer = current; }
})();
""" % {"binding": DATALAYER_BINDING}

# Lifecycle events every tool sends by itself; not proof an interaction was tracked.
LIFECYCLE_EVENTS = frozenset({
    "page_view", "pageview", "PageView", "session_start", "first_visit", "user_engagement",
    "scroll", "container_load", "gtag_script_load", "session_event", "activity",
    "gtm.js", "gtm.dom", "gtm.load", "gtm.init", "gtm.init_consent", "gtm.scrollDepth",
    "gtm.timer", "gtm.historyChange", "gtag:config", "gtag:js", "gtag:consent", "gtag:set",
})


@contextlib.asynccontextmanager
async def open_runtime_browser():
    """Chromium launch used by analytics checks and journey/."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await launch_chromium(pw)
        try:
            yield browser
        finally:
            await browser.close()


def _ga4_body_events(url: str, body: str) -> List[CapturedRequest]:
    """GA4 batches events in the POST body, one per line."""
    out: List[CapturedRequest] = []
    base_qs = parse_qs(urlparse(url).query)
    for line in (body or "").splitlines():
        line = line.strip()
        if not line:
            continue
        qs = {**base_qs, **parse_qs(line)}
        ev = (qs.get("en") or [None])[0]
        if ev:
            out.append(CapturedRequest(url=url, phase="", vendor_key="ga4", event_name=ev,
                                       is_page_view=(ev == "page_view"), identifier=(qs.get("tid") or [None])[0]))
    return out


def event_parameters(url: str, body_line: str = "") -> Dict[str, str]:
    """Readable event parameters from a hit (GA4, Meta, generic)."""
    qs = parse_qs(urlparse(url).query)
    if body_line:
        qs.update(parse_qs(body_line))
    params: Dict[str, str] = {}
    for k, v in qs.items():
        if k.startswith(("ep.", "epn.")):
            params[k.split(".", 1)[1]] = v[0]
        elif k.startswith("cd[") and k.endswith("]"):
            params[k[3:-1]] = v[0]
        elif k in ("dl", "dt", "link_url", "link_text", "file_name", "file_extension", "ev", "en"):
            params[k] = v[0]
    return params


def classify_analytics_request(url: str, post_data: Optional[str] = None) -> List[CapturedRequest]:
    """Classifies a hit and returns every event in it. [] = not an analytics hit."""
    base = _classify(url)
    if base is None:
        return []
    if base.vendor_key == "ga4" and post_data and "en=" in post_data:
        batched = _ga4_body_events(url, post_data)
        if batched:
            return batched
    return [base]
