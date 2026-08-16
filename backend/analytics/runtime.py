"""
analytics/runtime.py

The live half of analytics/. Every other file in this package answers
"is a tracker's code present in the markup" (ga4.py, gtm.py, adobe.py,
...) — that's Detection, and per the implementation requirements' §2
Core Validation Principle, detection alone never proves a tracker
actually works. This module answers Runtime Validation instead: it
opens the audited page in a real browser, watches the network tab, and
confirms a Page View request is actually sent, that scrolling and
clicking produce whatever events the implementation is supposed to
send for them, and that no vendor double-fires its Page View.

Flow (§3.2):
    1. clean browser context
    2. load the page, capture requests during load  -> Page View check
    3. scroll, capture new requests                 -> Scroll check
    4. click a safe interactive element, capture new requests -> Click check
    5. classify every captured request by vendor + event
    6. duplicate Page View check per vendor
    7. build one VendorRuntimeResult per vendor actually observed

Same degrade-gracefully contract as the rest of this codebase's
Playwright-backed modules (consent/network.py, consent/runtime.py,
crawler/screenshots.py): any failure yields available=False rather
than raising, so a runtime failure can never take down the rest of the
audit pipeline. A vendor that was never observed at runtime is
reported as runtime_tested=True / page_view_status="failed" (or
"not_tested" if the whole pass didn't run) — never silently upgraded
to a pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from config.logging import logger
from crawler.screenshots import DEFAULT_VIEWPORT, NAVIGATION_TIMEOUT_MS

MODULE = "analytics"
CATEGORY = "runtime"

SETTLE_MS = 1_500
SCROLL_SETTLE_MS = 1_200
CLICK_SETTLE_MS = 1_500

# Buttons/links a click-test must never hit — clicking Accept/Reject would
# contaminate this pass with consent side-effects that consent/runtime.py
# already tests independently and far more carefully.
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


# --------------------------------------------------------------------------
# Per-vendor request classification. Each rule matches on domain + path
# substrings (deliberately loose, same trade-off consent/network.py makes)
# and knows how to pull an event name / page-view flag / account id out of
# the query string for that vendor's collection endpoint.
# --------------------------------------------------------------------------

def _ga4_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    if "google-analytics.com" not in url and "analytics.google.com" not in url:
        return None
    if "/g/collect" not in url and "/collect" not in url and "/j/collect" not in url:
        return None
    event = (qs.get("en") or [None])[0]
    return CapturedRequest(url=url, phase="", vendor_key="ga4", event_name=event,
                            is_page_view=(event == "page_view"), identifier=(qs.get("tid") or [None])[0])


def _gtm_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    if "googletagmanager.com" not in url:
        return None
    # GTM-specific signatures only (§1.2) — a real container load
    # (/gtm.js) or its noscript fallback (/ns.html). Deliberately
    # excludes /gtag/js: that endpoint loads Google's *gtag.js* library,
    # which is how GA4 (and Google Ads) tags are installed directly
    # (without a GTM container) even though it's served from
    # googletagmanager.com — see _gtag_classify below. Conflating the
    # two used to misreport a site running GA4-via-gtag.js as running
    # Google Tag Manager, when no GTM container was ever installed.
    if "/gtm.js" not in url and "/ns.html" not in url:
        return None
    cid = (qs.get("id") or [None])[0]
    if cid and not cid.upper().startswith("GTM-"):
        return None  # id present but not a GTM container id — not actually GTM
    # GTM's own network signal is just "the container loaded" — unlike GA4/Adobe/etc.
    # it never sends its own page_view/scroll/click hits (those come from whatever
    # tags *inside* the container fire, which show up under their own vendor key).
    # Treating a successful container load as this vendor's "Page View" equivalent
    # matches §3.4's recommended display ("GTM ... Data Layer: Passed").
    return CapturedRequest(url=url, phase="", vendor_key="gtm", event_name="container_load",
                            is_page_view=True, identifier=cid)


def _gtag_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    """
    gtag.js (googletagmanager.com/gtag/js?id=...) is Google's direct
    tag-loading library — it's how a page installs GA4 (id starting
    "G-"), Google Ads (id starting "AW-"), or a handful of other Google
    products *without* a GTM container in between. It is never GTM
    itself, so this is kept as its own classifier rather than folded
    into _gtm_classify (§1.2's "correct gtag.js classification" fix).
    Only the GA4 case (id starts "G-") is attributed to the ga4 vendor
    key here; other gtag.js consumers (Ads, Floodlight) aren't analytics
    vendors this package tracks, so their loads are left unclassified
    rather than guessed at.
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
    is_pv = pe is None or pe == "pv"  # Adobe's "s.t()" page-view call sends no `pe` param; `pe=lnk_o` is a link/click
    event_name = "page_view" if is_pv else ("click" if pe == "lnk_o" else pe)
    return CapturedRequest(url=url, phase="", vendor_key="adobe", event_name=event_name,
                            is_page_view=is_pv, identifier=(qs.get("s_account") or qs.get("account") or [None])[0])


def _piano_classify(url: str, qs: Dict[str, List[str]]) -> Optional[CapturedRequest]:
    host = urlparse(url).hostname or ""
    if "aticdn.net" not in host and "piano.io" not in host and "xiti.com" not in host:
        return None
    if "event" not in url and "hit" not in url and "collect" not in url:
        return None
    event = (qs.get("events") or qs.get("event") or [None])[0]
    return CapturedRequest(url=url, phase="", vendor_key="piano", event_name=event or "page_view",
                            is_page_view=event is None, identifier=(qs.get("s") or qs.get("site") or [None])[0])


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


_CLASSIFIERS = [
    _ga4_classify, _gtm_classify, _gtag_classify, _adobe_classify, _piano_classify,
    _clarity_classify, _hotjar_classify, _meta_classify, _linkedin_classify, _tiktok_classify,
]

VENDOR_LABELS = {
    "ga4": "Google Analytics 4",
    "gtm": "Google Tag Manager",
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


async def run_analytics_runtime(url: str) -> AnalyticsRuntimeResult:
    """
    Full §3.2 runtime pass for one URL: Page View on load, Scroll,
    then a Click on a safe (non-consent) interactive element, each in
    the same fresh browser context so later requests can be attributed
    to the action that (probably) triggered them.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("analytics/runtime.py: playwright not installed — skipping analytics runtime validation")
        return AnalyticsRuntimeResult(available=False, error="playwright not installed")

    captured: List[CapturedRequest] = []
    phase = {"current": "load"}

    def _on_request(request):
        match = _classify(request.url)
        if match is not None:
            match.phase = phase["current"]
            captured.append(match)

    result = AnalyticsRuntimeResult(available=True, tested_at=datetime.now(timezone.utc).isoformat())

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                context = await browser.new_context(viewport=DEFAULT_VIEWPORT)
                page = await context.new_page()
                page.on("request", _on_request)

                # --- load / Page View ------------------------------------------------
                await page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
                await page.wait_for_timeout(SETTLE_MS)

                # --- scroll ------------------------------------------------------------
                phase["current"] = "scroll"
                try:
                    await page.mouse.wheel(0, 2500)
                    await page.wait_for_timeout(400)
                    await page.mouse.wheel(0, 2500)
                except Exception:  # noqa: BLE001 — a page with no scrollable content shouldn't abort the pass
                    pass
                await page.wait_for_timeout(SCROLL_SETTLE_MS)

                # --- click -------------------------------------------------------------
                phase["current"] = "click"
                clicked = await _click_safe_element(page)
                result.clicked_element = clicked
                await page.wait_for_timeout(CLICK_SETTLE_MS)
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 — a failed runtime pass should never break the audit
        logger.warning(f"analytics/runtime.py: runtime validation failed for {url}: {exc}")
        result.error = str(exc)
        result.available = bool(captured)  # keep whatever was captured before the failure, if anything

    result.vendors = _build_vendor_results(captured)
    return result


async def _click_safe_element(page) -> Optional[str]:
    """
    Clicks the first visible, non-consent-related <button> or in-page
    <a href="#..."> so the click-event test doesn't also trigger (and
    get confused with) a full page navigation or a consent action.
    Returns a short description of what was clicked, or None if
    nothing suitable was found.
    """
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


def _build_vendor_results(captured: List[CapturedRequest]) -> Dict[str, VendorRuntimeResult]:
    by_vendor: Dict[str, List[CapturedRequest]] = {}
    for req in captured:
        by_vendor.setdefault(req.vendor_key, []).append(req)

    results: Dict[str, VendorRuntimeResult] = {}
    for vendor_key, requests in by_vendor.items():
        load_reqs = [r for r in requests if r.phase == "load"]
        scroll_reqs = [r for r in requests if r.phase == "scroll"]
        click_reqs = [r for r in requests if r.phase == "click"]

        page_views_on_load = [r for r in load_reqs if r.is_page_view]
        identifier = next((r.identifier for r in requests if r.identifier), None)

        # GTM only ever emits one request (the container loading) — it has no
        # concept of its own scroll/click network hit, so those columns are
        # "not applicable" rather than a misleading "failed" for this vendor.
        # Any tag GTM fires *inside* the container shows up under that tag's
        # own vendor key (e.g. ga4) instead.
        if vendor_key == "gtm":
            scroll_status = NOT_APPLICABLE
            click_status = NOT_APPLICABLE
        else:
            scroll_status = PASSED if scroll_reqs else FAILED
            click_status = PASSED if click_reqs else FAILED

        vendor = VendorRuntimeResult(
            vendor_key=vendor_key,
            vendor_name=VENDOR_LABELS.get(vendor_key, vendor_key),
            detected=True,
            runtime_tested=True,
            identifier=identifier,
            page_view_status=PASSED if page_views_on_load else FAILED,
            scroll_status=scroll_status,
            click_status=click_status,
            custom_event_status=PASSED if any(
                r.event_name and not r.is_page_view for r in requests
            ) else NOT_APPLICABLE,
            duplicate_page_view=len(page_views_on_load) > 1,
            captured_request_count=len(requests),
            request_urls=[r.url for r in requests][:25],  # capped — evidence, not a full HAR dump
            event_names=sorted({r.event_name for r in requests if r.event_name}),
        )
        results[vendor_key] = vendor

    return results


def check_runtime_analytics(
    result: AnalyticsRuntimeResult,
    page_url: str,
    static_detected: Optional[Dict[str, bool]] = None,
) -> List[dict]:
    """
    Findings from an already-run AnalyticsRuntimeResult. `static_detected`
    (vendor_key -> bool, from analytics.detect_*().detected) lets this
    flag the Core Validation Principle's central case: a tracker present
    in markup that never actually fires — the gap detection-only results
    always miss. Empty list when runtime data wasn't available at all.
    """
    if not result.available:
        return []

    findings: List[dict] = []
    static_detected = static_detected or {}

    for vendor_key, static_present in static_detected.items():
        if not static_present:
            continue
        vendor = result.vendors.get(vendor_key)
        label = VENDOR_LABELS.get(vendor_key, vendor_key)
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
    """
    §1.2 — "Keep static Analytics detection separate from runtime
    validation... for every detected vendor, preserve the static
    detection result even if no runtime request is observed."

    `_build_vendor_results` only ever creates a VendorRuntimeResult for
    a vendor whose traffic was actually captured — a vendor that's
    detected in markup but never fires at runtime (the Core Validation
    Principle's central failure case) simply has no entry in
    `result.vendors` at all. Left alone, that means report.js's vendor
    table (built from `runtime_result.vendors`, §1.3) would silently
    drop that vendor's row instead of showing it as detected-but-failed.

    This mutates `result.vendors` in place, adding one entry for every
    statically-detected vendor missing from it, so every detected
    vendor is guaranteed a row:

      - runtime pass didn't run at all (`result.available` is False):
        every status stays NOT_TESTED/NOT_APPLICABLE (the dataclass
        defaults) — never reported as a failure when nothing was
        actually tested.
      - runtime pass ran but this vendor was never observed: page
        view/scroll/click are real evidence of absence, so they're
        marked FAILED (matching what `check_runtime_analytics` already
        assumes when `result.vendors.get(vendor_key)` is None);
        custom_event_status stays NOT_APPLICABLE — its absence isn't
        itself evidence of anything.

    Never overwrites an existing entry — a vendor runtime actually
    captured traffic for is real, richer evidence and always wins.
    """
    for vendor_key, detected in (static_detected or {}).items():
        if not detected or vendor_key in result.vendors:
            continue
        label = VENDOR_LABELS.get(vendor_key, vendor_key)
        if result.available:
            page_view_status = FAILED
            scroll_status = FAILED
            click_status = FAILED
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
