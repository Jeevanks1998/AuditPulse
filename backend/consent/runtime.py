"""
Live consent check in a real browser: find the cookie banner, list its
buttons, click them, and record cookies and requests afterwards.

The banner is found first (CMP selector, cookie dialog, CMP iframe, or the
smallest element about cookies that holds a consent button, including
iframes and shadow DOM). Only buttons inside it are ever clicked, so an
unrelated "Continue" or "OK" is never mistaken for Accept or Reject.

Each test runs in a fresh, empty browser:
  reject - before-consent capture, screenshot, click Reject (or open
           Settings to find it), capture after
  accept - click Accept, capture after
  manage - open Settings and record the panel (if not already done)
A test that can't run is "not tested", never a pass.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from config.logging import logger
from consent.buttons import (
    ACCEPT_ACTIONS,
    ACCEPT_CLICK_ORDER,
    CONSENT_ACTIONS,
    CONSENT_CONTAINER_SELECTORS,
    CONSENT_TEXT_PATTERN,
    EVIDENCE_RENDERED,
    MANAGE_ACTIONS,
    REJECT_ACTIONS,
    REJECT_CLICK_ORDER,
    SAVE_PREFERENCES,
    ButtonsDetection,
    ConsentControl,
    classify_label,
)
from consent.network import (  # noqa: F401 — KNOWN_TRACKER_DOMAINS re-exported for older callers
    KNOWN_TRACKER_DOMAINS,
    NetworkRequest,
    _classify,
    summarize_requests,
)
from cookies.categories import CONSENT_MANAGEMENT, ESSENTIAL, UNKNOWN, classify_cookie, requires_consent
from consent.screenshots import capture_page_or_element
from crawler.screenshots import DEFAULT_VIEWPORT, NAVIGATION_TIMEOUT_MS
from config.browser import launch_chromium
from consent.navigation import open_page, reload_page  # noqa: E402

MODULE = "consent"
CATEGORY = "runtime"

SETTLE_MS = 1_500          # wait after load for delayed requests
CLICK_SETTLE_MS = 2_500    # wait after a click for what it triggers
BANNER_RENDER_MS = 1_500   # minimum wait for a banner drawn by JavaScript
BANNER_MAX_WAIT_MS = 8_000  # keep checking for a late banner up to this long
BANNER_POLL_MS = 500

# Frames from these hosts are the consent window itself (Sourcepoint, TrustArc, ...).
_CMP_FRAME_HOSTS = (
    "privacy-mgmt.com", "sourcepoint.com", "consent.trustarc.com", "trustarc.com",
    "consensu.org", "quantcast.com", "fundingchoicesmessages.google.com", "cookiebot.com",
    "consentmanager.net", "usercentrics.eu", "privacy-center.org", "onetrust.com", "cookielaw.org",
)

CONTAINER_HANDLE = "__container__"

_VIA_SCORE = {"cmp_selector": 6, "cmp_iframe": 5, "aria_dialog": 4, "text_heuristic": 0}

# Runs in each frame: finds possible banners and the buttons inside them,
# marking each button so Python can click exactly that one. Looks inside
# shadow DOM too (Usercentrics).
_INVENTORY_JS = r"""
(args) => {
  const { selectors, consentText, maxText, isCmpFrame } = args;
  const consentRe = new RegExp(consentText, 'i');
  const verbRe = /accept|allow|agree|consent|reject|decline|deny|refuse|necessary|essential|required|without accept|akzept|ablehn|zustimm|notwendig|accepter|refuser|aceptar|rechazar|accett|rifiut/i;
  const CLICK_SEL = "button, [role='button'], a, input[type='button'], input[type='submit']";
  const TOGGLE_SEL = "input[type='checkbox'], [role='switch'], [role='checkbox']";
  window.__apCtlSeq = window.__apCtlSeq || 0;

  const deepQuery = (scope, sel) => {
    const out = [];
    const visit = (root) => {
      try { root.querySelectorAll(sel).forEach(e => out.push(e)); } catch (e) { return; }
      root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) visit(e.shadowRoot); });
    };
    if (scope.shadowRoot) visit(scope.shadowRoot);
    visit(scope);
    return out;
  };
  const deepText = (el) => {
    let t = (el.innerText || '');
    const hosts = [el, ...el.querySelectorAll('*')].filter(e => e.shadowRoot);
    for (const h of hosts) { t += ' ' + (h.shadowRoot.textContent || ''); }
    return t.replace(/\s+/g, ' ').trim();
  };
  const isVisible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.05) return false;
    return true;
  };
  const labelOf = (el) => {
    const t = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '');
    return t.replace(/\s+/g, ' ').trim();
  };
  const isClickable = (el) => {
    if (!isVisible(el)) return false;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) return true; // off-screen: Playwright scrolls
    const root = el.getRootNode();
    const hit = (root.elementFromPoint ? root.elementFromPoint(x, y) : document.elementFromPoint(x, y));
    if (!hit) return true;
    return hit === el || el.contains(hit) || (hit.closest && hit.closest(CLICK_SEL) === el) || hit.contains(el);
  };
  const parentOf = (el) => el.parentElement || (el.getRootNode() && el.getRootNode().host) || null;
  const describe = (el) => {
    if (el.id) return '#' + el.id;
    const cls = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/).filter(Boolean).slice(0, 3);
    return el.tagName.toLowerCase() + (cls.length ? '.' + cls.join('.') : '');
  };
  const isFixed = (el) => {
    let n = el, hops = 0;
    while (n && n.nodeType === 1 && hops < 10) {
      const p = getComputedStyle(n).position;
      if (p === 'fixed' || p === 'sticky') return true;
      n = parentOf(n); hops++;
    }
    return false;
  };
  const tooBig = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'html' || tag === 'body' || tag === 'main') return true;
    return deepText(el).length > maxText;
  };

  const cands = [];
  const seen = new Set();
  const add = (el, via, hint) => {
    if (!el || seen.has(el)) return;
    seen.add(el); cands.push({ el, via, hint });
  };

  for (const sel of selectors) {
    let found = [];
    try { found = deepQuery(document, sel); } catch (e) { continue; }
    for (const el of found) {
      if (!isVisible(el) && !(el.shadowRoot)) continue;
      if (tooBig(el)) continue;
      add(el, sel.startsWith('[role') ? 'aria_dialog' : 'cmp_selector', sel);
    }
  }
  for (const el of deepQuery(document, "[role='dialog'], [role='alertdialog'], dialog[open], [aria-modal='true']")) {
    if (!isVisible(el) || tooBig(el)) continue;
    if (consentRe.test(deepText(el))) add(el, 'aria_dialog', describe(el));
  }
  for (const btn of deepQuery(document, CLICK_SEL)) {
    if (!isVisible(btn)) continue;
    if (!verbRe.test(labelOf(btn))) continue;
    let n = parentOf(btn), hops = 0;
    while (n && n.nodeType === 1 && hops < 8) {
      if (tooBig(n)) break;
      if (consentRe.test(deepText(n))) { add(n, 'text_heuristic', describe(n)); break; }
      n = parentOf(n); hops++;
    }
  }
  if (isCmpFrame && document.body && cands.length === 0) {
    add(document.body, 'cmp_iframe', location.hostname);
  }

  return cands.map((c) => {
    const ctls = [];
    const els = deepQuery(c.el, CLICK_SEL);
    if (c.el.matches && c.el.matches(CLICK_SEL)) els.unshift(c.el);
    for (const e of els) {
      const label = labelOf(e);
      if (!label || label.length > 120) continue;
      let id = e.getAttribute('data-auditpulse-ctl');
      if (!id) { id = String(++window.__apCtlSeq); e.setAttribute('data-auditpulse-ctl', id); }
      ctls.push({ id, label, tag: e.tagName.toLowerCase(), visible: isVisible(e), clickable: isClickable(e) });
    }
    const text = deepText(c.el);
    window.__apBoxSeq = window.__apBoxSeq || 0;
    let box = c.el.getAttribute && c.el.getAttribute('data-auditpulse-box');
    if (!box && c.el.setAttribute) { box = String(++window.__apBoxSeq); c.el.setAttribute('data-auditpulse-box', box); }
    return {
      via: c.via, hint: c.hint, describe: describe(c.el), fixed: isFixed(c.el), box,
      isBody: c.el === document.body,
      textLen: text.length, excerpt: text.slice(0, 600),
      toggles: deepQuery(c.el, TOGGLE_SEL).length,
      controls: ctls,
    };
  });
}
"""


@dataclass
class CookieSnapshot:
    name: str
    domain: str
    category: str  # essential / functional / analytics / marketing / consent_management / unknown
    purpose: str = "unknown"
    vendor: Optional[str] = None
    # Full cookie details for the Cookie Scanner. Defaults keep older saved results loadable.
    path: str = "/"
    expires: Optional[float] = None   # epoch seconds; None = session cookie
    secure: bool = False
    http_only: bool = False
    same_site: Optional[str] = None
    size: int = 0


@dataclass
class ConsentStateCapture:
    """What was seen at one point: before consent, after Reject or after Accept."""

    available: bool = False
    cookies: List[CookieSnapshot] = field(default_factory=list)
    requests: List[NetworkRequest] = field(default_factory=list)
    error: Optional[str] = None
    page_url: Optional[str] = None   # page open at capture time
    # localStorage / sessionStorage keys at capture time.
    local_storage_keys: List[str] = field(default_factory=list)
    session_storage_keys: List[str] = field(default_factory=list)

    @property
    def tracker_requests(self) -> List[NetworkRequest]:
        """Real tracking hits only."""
        return [r for r in self.requests if r.is_tracking]

    @property
    def vendor_requests(self) -> List[NetworkRequest]:
        """Any request to a known tracking vendor (loaders included)."""
        return [r for r in self.requests if r.tracker_name]

    @property
    def consent_required_cookies(self) -> List[CookieSnapshot]:
        """Analytics + marketing cookies: the only ones that count as a failure."""
        return [c for c in self.cookies if requires_consent(c.category)]

    @property
    def non_essential_cookies(self) -> List[CookieSnapshot]:
        """Older name. Doesn't include unknown, consent-tool or functional cookies."""
        return self.consent_required_cookies

    @property
    def unknown_cookies(self) -> List[CookieSnapshot]:
        return [c for c in self.cookies if c.category == UNKNOWN]

    @property
    def consent_management_cookies(self) -> List[CookieSnapshot]:
        return [c for c in self.cookies if c.category == CONSENT_MANAGEMENT]

    @property
    def essential_cookies(self) -> List[CookieSnapshot]:
        return [c for c in self.cookies if c.category == ESSENTIAL]


@dataclass
class BannerInventory:
    """The rendered banner and its buttons."""
    banner_detected: bool = False
    detected_via: Optional[str] = None   # cmp_selector | aria_dialog | cmp_iframe | text_heuristic
    container: Optional[str] = None       # selector / id / class of the banner
    frame: str = "main"
    text_excerpt: str = ""
    is_overlay: bool = False              # position fixed/sticky
    toggle_count: int = 0                 # category switches inside
    controls: List[ConsentControl] = field(default_factory=list)
    # Selector for the banner element, used to crop screenshots. Not saved.
    element_selector: Optional[str] = None

    def first(self, order) -> Optional[ConsentControl]:
        """First button matching the preferred actions, visible ones first."""
        for action in order:
            matches = [c for c in self.controls if c.action == action]
            matches.sort(key=lambda c: (not c.clickable, not c.visible))
            if matches:
                return matches[0]
        return None

    def as_dict(self) -> dict:
        return {
            "banner_detected": self.banner_detected, "detected_via": self.detected_via,
            "container": self.container, "frame": self.frame, "text_excerpt": self.text_excerpt,
            "is_overlay": self.is_overlay, "toggle_count": self.toggle_count,
            "controls": [c.as_dict() for c in self.controls],
        }


@dataclass
class ConsentRuntimeResult:
    available: bool = False
    error: Optional[str] = None

    # Buttons on the banner (layer 1) and, if opened, the settings panel (layer 2).
    banner: Optional[dict] = None
    controls: List[ConsentControl] = field(default_factory=list)
    preference_panel: Optional[dict] = None
    preference_controls: List[ConsentControl] = field(default_factory=list)

    accept_button_found: bool = False
    reject_button_found: bool = False      # on any layer (see reject_layer)
    manage_button_found: bool = False
    reject_layer: Optional[int] = None     # 1 = banner, 2 = settings panel only

    # The browser saw a banner. False only means "not seen"; it never disproves the static check.
    banner_detected: bool = False

    accept_clicked: bool = False
    reject_clicked: bool = False
    manage_clicked: bool = False
    accept_clicked_label: Optional[str] = None
    reject_clicked_label: Optional[str] = None
    manage_clicked_label: Optional[str] = None

    before_consent: ConsentStateCapture = field(default_factory=ConsentStateCapture)
    after_reject: ConsentStateCapture = field(default_factory=ConsentStateCapture)
    # The next page after Reject: catches tracking that comes back on the next page view.
    after_reject_reload: ConsentStateCapture = field(default_factory=ConsentStateCapture)
    # Accept test's starting state, compared with after Accept.
    before_accept: ConsentStateCapture = field(default_factory=ConsentStateCapture)
    after_accept: ConsentStateCapture = field(default_factory=ConsentStateCapture)

    # Unique per run, used in screenshot file names so old evidence is never reused.
    scan_id: Optional[str] = None
    fresh_contexts: int = 0
    leg_log: List[str] = field(default_factory=list)

    initial_banner_screenshot: Optional[str] = None
    preferences_screenshot: Optional[str] = None
    reject_screenshot: Optional[str] = None
    accept_screenshot: Optional[str] = None

    # Results: None means "not tested", never a pass.
    reject_blocks_tracking: Optional[bool] = None
    # After Accept: a control that re-opens the cookie settings, and whether it worked.
    withdrawal_control_label: Optional[str] = None
    withdrawal_reopens: Optional[bool] = None
    accept_allows_tracking: Optional[bool] = None
    personalize_exposes_controls: Optional[bool] = None

    # Request summaries per category for the report.
    network_summary: Dict[str, dict] = field(default_factory=dict)

    # Cookie Scanner: after Accept, other pages visited with consent given: {url, cookies_set}.
    site_pages: List[dict] = field(default_factory=list)

    tested_at: Optional[str] = None

    def buttons_detection(self) -> ButtonsDetection:
        """The rendered buttons as a ButtonsDetection."""
        banner = self.banner or {}
        return ButtonsDetection.from_controls(
            self.controls + self.preference_controls,
            container_found=self.banner_detected,
            container_hint=banner.get("container"),
            detected_via=banner.get("detected_via"),
            source="runtime",
        )


# Banner inventory

def _is_cmp_frame(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _CMP_FRAME_HOSTS)


async def inventory_banner(
    page, layer: int = 1, avoid_container: Optional[str] = None,
) -> Tuple[BannerInventory, Dict[str, object]]:
    """Scans every frame for the banner. Returns (inventory, handles) so the exact button can be clicked."""
    best: Optional[Tuple[int, dict, object, str]] = None
    main = page.main_frame
    for frame in list(page.frames):
        try:
            frame_url = frame.url or ""
            cands = await frame.evaluate(_INVENTORY_JS, {
                "selectors": CONSENT_CONTAINER_SELECTORS,
                "consentText": CONSENT_TEXT_PATTERN,
                "maxText": 4000,
                "isCmpFrame": frame is not main and _is_cmp_frame(frame_url),
            })
        except Exception:  # noqa: BLE001 — detached / cross-origin-blocked frame
            continue
        for cand in cands or []:
            actions = [classify_label(c["label"]) for c in cand.get("controls", [])]
            n_accept = sum(1 for a in actions if a in ACCEPT_ACTIONS)
            n_reject = sum(1 for a in actions if a in REJECT_ACTIONS)
            n_manage = sum(1 for a in actions if a in MANAGE_ACTIONS or a == SAVE_PREFERENCES)
            via = cand.get("via")
            # A text-matched element must hold Accept or Reject; selector/dialog/iframe matches count on their own.
            if via == "text_heuristic" and not (n_accept or n_reject):
                continue
            if via != "text_heuristic" and not (n_accept or n_reject or n_manage) and not cand.get("controls"):
                continue
            score = (n_accept + n_reject) * 10 + n_manage * 3 + _VIA_SCORE.get(via, 0) \
                + (2 if cand.get("fixed") else 0) - min(cand.get("textLen", 0), 4000) // 1000
            frame_label = "main" if frame is main else frame_url
            if layer == 2:
                # Settings panel: prefer the element with category switches that isn't the banner itself.
                score += min(int(cand.get("toggles") or 0), 10) * 2
                if avoid_container and avoid_container in (cand.get("hint"), cand.get("describe")):
                    score -= 15
            if best is None or score > best[0]:
                best = (score, cand, frame, frame_label)

    if best is None:
        return BannerInventory(banner_detected=False), {}

    _, cand, frame, frame_label = best
    evidence = EVIDENCE_RENDERED if frame_label == "main" else \
        f"{EVIDENCE_RENDERED} (iframe: {urlparse(frame_label).hostname or frame_label})"
    if layer == 2:
        evidence = "Rendered preference panel" + ("" if frame_label == "main" else
                                                  f" (iframe: {urlparse(frame_label).hostname or frame_label})")

    controls: List[ConsentControl] = []
    handles: Dict[str, object] = {}
    seen = set()
    for c in cand.get("controls", []):
        label = c["label"]
        action = classify_label(label)
        key = (label, action)
        if key in seen:
            continue
        seen.add(key)
        selector = f'[data-auditpulse-ctl="{c["id"]}"]'
        controls.append(ConsentControl(
            label=label, action=action, evidence=evidence, selector=selector, frame=frame_label,
            visible=bool(c.get("visible")), clickable=bool(c.get("clickable")), layer=layer, tag=c.get("tag"),
        ))
        handles[selector] = frame

    element_selector = None
    if cand.get("box"):
        element_selector = "body" if cand.get("isBody") else f'[data-auditpulse-box="{cand["box"]}"]'
        handles[CONTAINER_HANDLE] = (frame, element_selector)

    inv = BannerInventory(
        banner_detected=True, detected_via=cand.get("via"),
        container=cand.get("hint") if cand.get("via") != "text_heuristic" else cand.get("describe"),
        frame=frame_label, text_excerpt=cand.get("excerpt", ""), is_overlay=bool(cand.get("fixed")),
        toggle_count=int(cand.get("toggles") or 0), controls=controls, element_selector=element_selector,
    )
    return inv, handles


async def _wait_for_banner(page) -> Tuple[BannerInventory, Dict[str, object]]:
    """Waits for a (possibly late) banner, up to BANNER_MAX_WAIT_MS."""
    await page.wait_for_timeout(BANNER_RENDER_MS)
    waited = BANNER_RENDER_MS
    inv, handles = await inventory_banner(page)
    while not (inv.banner_detected and any(c.action in CONSENT_ACTIONS for c in inv.controls)) \
            and waited < BANNER_MAX_WAIT_MS:
        await page.wait_for_timeout(BANNER_POLL_MS)
        waited += BANNER_POLL_MS
        inv, handles = await inventory_banner(page)
    return inv, handles


async def _click_control(page, handles: Dict[str, object], control: ConsentControl, layer: int = 1) -> bool:
    """Clicks exactly the listed button; re-scans once if the page re-rendered."""
    for attempt in range(2):
        frame = handles.get(control.selector) if control.selector else None
        if frame is not None:
            try:
                loc = frame.locator(control.selector).first
                if await loc.count() > 0:
                    try:
                        await loc.click(timeout=5_000)
                    except Exception:  # noqa: BLE001 — overlay intercepting pointer events
                        await loc.evaluate("el => el.click()")
                    return True
            except Exception as exc:  # noqa: BLE001
                logger.info(f"consent/runtime.py: click on '{control.label}' failed: {exc}")
        if attempt == 0:
            inv, handles = await inventory_banner(page, layer=layer)
            match = next((c for c in inv.controls if c.label == control.label and c.action == control.action), None)
            if match is None:
                return False
            control = match
    return False


# Main flow

async def run_consent_runtime(url: str, scan_id: Optional[str] = None,
                              browse_urls: Optional[List[str]] = None) -> ConsentRuntimeResult:
    """Fresh consent check: every test uses a new, empty browser and its own
    screenshots (named with scan_id).
      Test 1: load, banner, screenshot, cookies, requests, buttons; open Settings
              if present; click Reject; capture; screenshot.
      Test 2: load, click Accept, capture, screenshot.
    Nothing is assumed: a missing Accept is reported, not invented.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("consent/runtime.py: playwright not installed — skipping consent runtime validation")
        return ConsentRuntimeResult(available=False, error="playwright not installed")

    scan_id = scan_id or new_scan_id()
    result = ConsentRuntimeResult(available=False, tested_at=datetime.now(timezone.utc).isoformat(), scan_id=scan_id)
    hostname = urlparse(url).hostname or ""

    try:
        async with async_playwright() as pw:
            browser = await launch_chromium(pw)
            result.available = True
            try:
                try:
                    await _run_leg_one(browser, url, hostname, result)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"consent/runtime.py: leg 1 (preferences/reject) failed for {url}: {exc}")
                    result.leg_log.append(f"leg 1 failed: {exc}")
                    if not result.before_consent.available:
                        result.before_consent = ConsentStateCapture(available=False, error=str(exc))
                    if not result.after_reject.available:
                        result.after_reject = ConsentStateCapture(available=False, error=str(exc))

                try:
                    await _run_leg_two(browser, url, hostname, result, browse_urls or [])
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"consent/runtime.py: leg 2 (accept) failed for {url}: {exc}")
                    result.leg_log.append(f"leg 2 failed: {exc}")
                    if not result.after_accept.available:
                        result.after_accept = ConsentStateCapture(available=False, error=str(exc))
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 — a failed runtime pass should never break the audit
        logger.warning(f"consent/runtime.py: runtime consent validation failed for {url}: {exc}")
        result.error = str(exc)

    _derive_verdicts(result)
    return result


def new_scan_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]


async def _fresh_context(browser, result: ConsentRuntimeResult):
    """New isolated browser context: no cookies, storage or cache."""
    context = await browser.new_context(
        viewport=DEFAULT_VIEWPORT,
        storage_state=None,
        service_workers="block",
        ignore_https_errors=False,
    )
    result.fresh_contexts += 1
    return context


def _record_inventory(result: ConsentRuntimeResult, inv: BannerInventory) -> None:
    if result.banner is None or not result.banner.get("banner_detected"):
        result.banner = inv.as_dict()
        result.controls = list(inv.controls)


async def _open_preferences(page, handles, inv: BannerInventory, result: ConsentRuntimeResult, url: str,
                            leg: int = 1):
    """Clicks Settings and checks a preference panel really appeared."""
    manage = inv.first(tuple(MANAGE_ACTIONS))
    if manage is None:
        return None, {}
    if not await _click_control(page, handles, manage):
        result.leg_log.append(f"leg {leg}: could not click '{manage.label}'")
        return None, {}
    await page.wait_for_timeout(CLICK_SETTLE_MS)
    result.manage_clicked = True
    result.manage_clicked_label = manage.label
    panel, panel_handles = await inventory_banner(page, layer=2, avoid_container=inv.container)
    if (panel.banner_detected and panel.container == inv.container and panel.frame == inv.frame
            and panel.toggle_count == 0
            and [(c.label, c.action) for c in panel.controls] == [(c.label, c.action) for c in inv.controls]):
        # Same banner, no category switches: the click opened nothing.
        panel = BannerInventory(banner_detected=False)
        panel_handles = {}
    result.preference_panel = panel.as_dict()
    result.preference_controls = list(panel.controls)
    result.personalize_exposes_controls = bool(
        panel.banner_detected and (
            panel.toggle_count > 0
            or any(c.action == SAVE_PREFERENCES or c.action in REJECT_ACTIONS or c.action in ACCEPT_ACTIONS
                   for c in panel.controls)
        )
    )
    result.preferences_screenshot = await _capture(
        page, url, "consent_preferences", result.scan_id,
        panel_handles.get(CONTAINER_HANDLE) if panel.banner_detected else None,
    )
    result.leg_log.append(
        f"leg {leg}: clicked '{manage.label}' → preference panel "
        + ("appeared" if result.personalize_exposes_controls else "did not appear"))
    return panel, panel_handles


async def _run_leg_one(browser, url: str, hostname: str, result: ConsentRuntimeResult) -> None:
    context = await _fresh_context(browser, result)
    try:
        page = await context.new_page()
        sink: List[NetworkRequest] = []
        page.on("request", lambda r: sink.append(_classify(r.url, r.resource_type, hostname)))

        await open_page(page, url, NAVIGATION_TIMEOUT_MS)
        inv, handles = await _wait_for_banner(page)
        if SETTLE_MS > BANNER_RENDER_MS:
            await page.wait_for_timeout(SETTLE_MS - BANNER_RENDER_MS)

        _record_inventory(result, inv)
        result.initial_banner_screenshot = await _capture(
            page, url, "consent_initial", result.scan_id,
            handles.get(CONTAINER_HANDLE) if inv.banner_detected else None,
        )
        result.before_consent = await _state(context, page, sink)
        result.leg_log.append(
            f"leg 1: fresh context, banner {'detected (' + str(inv.container) + ')' if inv.banner_detected else 'not detected'}, "
            f"{len(inv.controls)} control(s): " + ", ".join(f"'{c.label}'→{c.action}" for c in inv.controls))

        if not inv.banner_detected:
            result.after_reject = ConsentStateCapture(available=False, error="consent banner not detected")
            return

        first_layer_reject = inv.first(REJECT_CLICK_ORDER)
        result.reject_layer = 1 if first_layer_reject else None

        # Test the Reject visitors see: the banner's own when there is one; otherwise open Settings to find it.
        panel, panel_handles = (None, {})
        if first_layer_reject is None:
            panel, panel_handles = await _open_preferences(page, handles, inv, result, url)

        # Use the Reject on screen now; never invent one.
        reject, reject_handles, layer = None, handles, 1
        if first_layer_reject is not None:
            reject, reject_handles, layer = first_layer_reject, handles, 1
        elif panel is not None and panel.banner_detected:
            reject = panel.first(REJECT_CLICK_ORDER)
            reject_handles, layer = panel_handles, 2
        if reject is None:
            current, current_handles = await inventory_banner(page)
            reject = current.first(REJECT_CLICK_ORDER) if current.banner_detected else None
            reject_handles, layer = current_handles, 1
        if reject is None and first_layer_reject is not None and result.manage_clicked:
            # The panel replaced the banner and has no Reject: record it as not reachable.
            result.leg_log.append("leg 1: first-layer reject not reachable after opening preferences")
        if result.reject_layer is None and reject is not None:
            result.reject_layer = 2

        if reject is None:
            result.after_reject = ConsentStateCapture(available=False, error="reject control not found in banner")
            result.leg_log.append("leg 1: no reject control present — reject not tested")
            return

        mark = len(sink)
        if not await _click_control(page, reject_handles, reject, layer=layer):
            result.after_reject = ConsentStateCapture(available=False, error=f"could not click '{reject.label}'")
            return
        result.reject_clicked = True
        result.reject_clicked_label = reject.label
        await page.wait_for_timeout(CLICK_SETTLE_MS)

        result.after_reject = await _state(context, page, sink[mark:])
        result.reject_screenshot = await _capture(page, url, "consent_reject", result.scan_id)
        result.leg_log.append(f"leg 1: clicked '{reject.label}' ({reject.action})")

        # Load the next page with Reject stored: tags that fire on page load show up here.
        mark = len(sink)
        try:
            await reload_page(page, NAVIGATION_TIMEOUT_MS)
            await page.wait_for_timeout(SETTLE_MS + CLICK_SETTLE_MS)
            result.after_reject_reload = await _state(context, page, sink[mark:])
            n = len(result.after_reject_reload.tracker_requests)
            result.leg_log.append(f"leg 1: reloaded the page after reject — {n} tracking request(s) on the next page view")
        except Exception as exc:  # noqa: BLE001 — the click-time capture still stands on its own
            result.after_reject_reload = ConsentStateCapture(available=False, error=str(exc)[:200])
            result.leg_log.append(f"leg 1: reload after reject failed: {str(exc)[:120]}")
    finally:
        await context.close()


# Every link/button on the page after Accept, to find a "change my cookie choice" control.
_WITHDRAWAL_CANDIDATES_JS = r"""
() => {
  const TRIGGER = /ot-sdk-btn|ot-sdk-show-settings|optanon-show-settings|CookiebotWidget|cky-btn-revisit|osano-cm-widget|qc-cmp2-toggle-link|iubenda-cs-preferences-link|cmplz-manage|didomi.*preferences|tc_privacy_center|privacy-center|uc-privacy-button|cookie-?settings|cookie-?preferences/i;
  const out = [];
  const els = Array.from(document.querySelectorAll('a, button, [role=button], [onclick]'));
  els.forEach((el, i) => {
    const label = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').replace(/\s+/g, ' ').trim();
    const hint = (el.id || '') + ' ' + (typeof el.className === 'string' ? el.className : '') + ' ' + (el.getAttribute('onclick') || '') + ' ' + (el.getAttribute('href') || '');
    if (!label && !TRIGGER.test(hint)) return;
    if (label.length > 80) return;
    const href = el.tagName === 'A' ? (el.getAttribute('href') || '') : '';
    const navigates = !!href && !/^(#|javascript:)/i.test(href);
    el.setAttribute('data-ap-withdraw', String(i));
    out.push({ i, label, trigger: TRIGGER.test(hint), navigates });
  });
  return out.slice(0, 600);
}
"""


async def _check_withdrawal(page, result: ConsentRuntimeResult) -> None:
    """After Accept: click a control that re-opens cookie settings; verified if a banner/panel appears."""
    from consent.buttons import MANAGE_PREFERENCES, classify_label
    from consent.preferences import _LINK_TEXT_RE

    cands = await page.evaluate(_WITHDRAWAL_CANDIDATES_JS) or []

    def score(c):
        if c.get("navigates"):
            return 0                     # a link to the cookie policy page doesn't withdraw consent
        lbl = c.get("label") or ""
        if c.get("trigger"):
            return 3
        if classify_label(lbl) == MANAGE_PREFERENCES or _LINK_TEXT_RE.search(lbl):
            return 2
        return 0

    ranked = sorted((c for c in cands if score(c) > 0), key=lambda c: -score(c))
    if not ranked:
        result.withdrawal_reopens = False
        result.leg_log.append("leg 2: no control to re-open the cookie settings was found after accepting")
        return
    for c in ranked[:3]:
        loc = page.locator(f'[data-ap-withdraw="{c["i"]}"]').first
        try:
            try:
                await loc.click(timeout=3_000)
            except Exception:  # noqa: BLE001 — hidden/covered: DOM click
                await loc.evaluate("el => el.click()")
        except Exception:  # noqa: BLE001
            continue
        await page.wait_for_timeout(CLICK_SETTLE_MS)
        inv, _ = await inventory_banner(page)
        if inv.banner_detected and (inv.toggle_count or any(ct.action in CONSENT_ACTIONS for ct in inv.controls)):
            result.withdrawal_control_label = c.get("label") or "cookie settings trigger"
            result.withdrawal_reopens = True
            result.leg_log.append(f"leg 2: clicked '{result.withdrawal_control_label}' after accepting → cookie settings re-opened")
            return
    result.withdrawal_control_label = ranked[0].get("label")
    result.withdrawal_reopens = False
    result.leg_log.append(f"leg 2: '{result.withdrawal_control_label}' was clicked but no cookie settings appeared")


async def _run_leg_two(browser, url: str, hostname: str, result: ConsentRuntimeResult,
                       browse_urls: Optional[List[str]] = None) -> None:
    context = await _fresh_context(browser, result)
    try:
        page = await context.new_page()
        sink: List[NetworkRequest] = []
        page.on("request", lambda r: sink.append(_classify(r.url, r.resource_type, hostname)))
        await open_page(page, url, NAVIGATION_TIMEOUT_MS)
        inv, handles = await _wait_for_banner(page)
        _record_inventory(result, inv)
        result.before_accept = await _state(context, page, sink)

        # Open the settings panel if test 1 didn't, then reload so Accept is tested from the banner.
        if inv.banner_detected and not result.manage_clicked and inv.first(tuple(MANAGE_ACTIONS)):
            panel, _ = await _open_preferences(page, handles, inv, result, url, leg=2)
            if panel is not None and panel.banner_detected and result.reject_layer is None:
                if panel.first(REJECT_CLICK_ORDER):
                    result.reject_layer = 2
            try:
                await reload_page(page, NAVIGATION_TIMEOUT_MS)
                inv, handles = await _wait_for_banner(page)
            except Exception as exc:  # noqa: BLE001
                result.leg_log.append(f"leg 2: reload after preferences failed: {str(exc)[:120]}")
                inv, handles = BannerInventory(banner_detected=False), {}
            if not (inv.banner_detected and inv.first(ACCEPT_CLICK_ORDER)):
                # Banner didn't come back after the panel visit: test Accept in a fresh browser.
                await context.close()
                context = await _fresh_context(browser, result)
                page = await context.new_page()
                sink = []
                page.on("request", lambda r: sink.append(_classify(r.url, r.resource_type, hostname)))
                await open_page(page, url, NAVIGATION_TIMEOUT_MS)
                inv, handles = await _wait_for_banner(page)
                result.leg_log.append("leg 2: banner reloaded in a fresh context for the Accept test")

        accept = inv.first(ACCEPT_CLICK_ORDER) if inv.banner_detected else None
        if accept is None:
            result.after_accept = ConsentStateCapture(
                available=False,
                error="accept control not found in banner" if inv.banner_detected else "consent banner not detected",
            )
            result.leg_log.append("leg 2: no accept control present — accept not tested")
            return

        mark = len(sink)
        if not await _click_control(page, handles, accept):
            result.after_accept = ConsentStateCapture(available=False, error=f"could not click '{accept.label}'")
            return
        result.accept_clicked = True
        result.accept_clicked_label = accept.label
        await page.wait_for_timeout(CLICK_SETTLE_MS)

        result.after_accept = await _state(context, page, sink[mark:])
        result.accept_screenshot = await _capture(page, url, "consent_accept", result.scan_id)
        result.leg_log.append(f"leg 2: fresh context, clicked '{accept.label}' ({accept.action})")
        # Late tags set cookies after the first capture: scroll, wait, capture again.
        try:
            await _scroll_and_settle(page)
            later = await _snapshot_cookies(context)
            known = {(c.name, c.domain, c.path) for c in result.after_accept.cookies}
            result.after_accept.cookies += [c for c in later if (c.name, c.domain, c.path) not in known]
        except Exception as exc:  # noqa: BLE001
            result.leg_log.append(f"leg 2: late-cookie capture failed: {str(exc)[:120]}")
        try:
            await _check_withdrawal(page, result)
        except Exception as exc:  # noqa: BLE001 — never lose the accept evidence over this
            result.leg_log.append(f"leg 2: withdrawal check failed: {str(exc)[:120]}")
        if browse_urls:
            try:
                await _browse_for_cookies(context, page, browse_urls, result)
            except Exception as exc:  # noqa: BLE001 — the homepage evidence above stands on its own
                result.leg_log.append(f"leg 2: cookie browse failed: {str(exc)[:120]}")
    finally:
        await context.close()


BROWSE_PAGE_SETTLE_MS = 1_500
BROWSE_SCROLL_SETTLE_MS = 1_500
BROWSE_NAV_TIMEOUT_MS = 20_000
# About 15 pages (8-12 s each). The consent module gets this much extra time while browsing.
BROWSE_BUDGET_S = 210


async def _scroll_and_settle(page, settle_ms: int = 3_000) -> None:
    """Scrolls through the page and waits, to catch late tags."""
    try:
        await page.evaluate(
            "async () => { const h = document.body ? document.body.scrollHeight : 0;"
            " for (let y = 0; y < h; y += Math.max(400, h / 6)) { window.scrollTo(0, y);"
            " await new Promise(r => setTimeout(r, 250)); } window.scrollTo(0, 0); }")
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(settle_ms)


async def _browse_for_cookies(context, page, urls: List[str], result: ConsentRuntimeResult) -> None:
    """Visits other pages with consent given and records the cookies each adds."""
    import time as _time

    seen = {(c.name, c.domain, c.path) for c in result.after_accept.cookies}
    seen |= {(c.name, c.domain, c.path) for c in result.after_reject.cookies}
    started = _time.monotonic()
    visited = 0
    for target in urls:
        if _time.monotonic() - started > BROWSE_BUDGET_S:
            result.leg_log.append(f"cookie browse: time budget reached after {visited} page(s)")
            break
        try:
            try:
                await open_page(page, target, BROWSE_NAV_TIMEOUT_MS)
            except Exception:  # noqa: BLE001 — slow "load" (endless trackers): use what has rendered
                if not page.url or page.url == "about:blank":
                    raise
            await page.wait_for_timeout(BROWSE_PAGE_SETTLE_MS)
            await _scroll_and_settle(page, BROWSE_SCROLL_SETTLE_MS)
        except Exception as exc:  # noqa: BLE001 — one slow page never stops the sweep
            result.site_pages.append({"url": target, "error": str(exc)[:160], "cookies_set": []})
            continue
        visited += 1
        new = []
        for c in await _snapshot_cookies(context):
            key = (c.name, c.domain, c.path)
            if key in seen:
                continue
            seen.add(key)
            new.append({"name": c.name, "domain": c.domain, "path": c.path, "expires": c.expires,
                        "secure": c.secure, "http_only": c.http_only, "same_site": c.same_site,
                        "size": c.size})
        result.site_pages.append({"url": page.url or target, "cookies_set": new})
    result.leg_log.append(f"cookie browse: {visited} page(s) visited with consent accepted")


async def _state(context, page, requests: List[NetworkRequest]) -> ConsentStateCapture:
    local_keys, session_keys = [], []
    try:
        keys = await page.evaluate(
            "() => { try { return [Object.keys(localStorage), Object.keys(sessionStorage)]; }"
            " catch (e) { return [[], []]; } }")
        local_keys, session_keys = keys[0][:50], keys[1][:50]
    except Exception:  # noqa: BLE001
        pass
    try:
        page_url = page.url
    except Exception:  # noqa: BLE001
        page_url = None
    return ConsentStateCapture(
        available=True,
        page_url=page_url,
        cookies=await _snapshot_cookies(context),
        requests=list(requests),
        local_storage_keys=local_keys,
        session_storage_keys=session_keys,
    )


async def _snapshot_cookies(context) -> List[CookieSnapshot]:
    raw = await context.cookies()
    out = []
    for c in raw:
        cls = classify_cookie(c["name"], c.get("domain"))
        exp = c.get("expires")
        out.append(CookieSnapshot(name=c["name"], domain=c.get("domain", ""), category=cls.category,
                                  purpose=cls.purpose, vendor=cls.vendor, path=c.get("path") or "/",
                                  expires=float(exp) if isinstance(exp, (int, float)) and exp > 0 else None,
                                  secure=bool(c.get("secure")), http_only=bool(c.get("httpOnly")),
                                  same_site=c.get("sameSite") or None,
                                  size=len(c.get("name") or "") + len(c.get("value") or "")))
    return out


async def _capture(page, url: str, hint: str, scan_id: Optional[str] = None, element=None) -> Optional[str]:
    """Screenshot, cropped to the banner when given."""
    return await capture_page_or_element(page, url, hint, scan_id=scan_id, element=element)


def _derive_verdicts(result: ConsentRuntimeResult) -> None:
    """Turns the captures into results. None ("not tested") when a test didn't run."""
    first_layer = result.controls
    all_controls = result.controls + result.preference_controls

    result.banner_detected = bool(result.available and result.banner and result.banner.get("banner_detected"))
    result.accept_button_found = any(c.action in ACCEPT_ACTIONS for c in first_layer)
    result.manage_button_found = any(c.action in MANAGE_ACTIONS for c in first_layer)
    result.reject_button_found = any(c.action in REJECT_ACTIONS for c in all_controls)
    if result.reject_layer is None and result.reject_button_found:
        result.reject_layer = 1 if any(c.action in REJECT_ACTIONS for c in first_layer) else 2

    before_names = {(c.name, c.domain) for c in result.before_consent.consent_required_cookies}

    if result.after_reject.available:
        captures = [result.after_reject] + ([result.after_reject_reload] if result.after_reject_reload.available else [])
        trackers = [r for cap in captures for r in cap.tracker_requests]
        new_cookies = [c for cap in captures for c in cap.consent_required_cookies
                       if (c.name, c.domain) not in before_names]
        result.reject_blocks_tracking = not trackers and not new_cookies

    if result.after_accept.available:
        new_trackers = len(result.after_accept.tracker_requests) > 0
        baseline = result.before_accept if result.before_accept.available else result.before_consent
        accept_before = {(c.name, c.domain) for c in baseline.consent_required_cookies}
        new_cookies = any((c.name, c.domain) not in accept_before
                          for c in result.after_accept.consent_required_cookies)
        result.accept_allows_tracking = new_trackers or new_cookies

    summary: Dict[str, dict] = {}
    if result.before_consent.available:
        summary["before_consent"] = summarize_requests(result.before_consent.requests)
    if result.after_reject.available:
        summary["after_reject"] = summarize_requests(result.after_reject.requests)
    if result.after_reject_reload.available:
        summary["after_reject_next_page"] = summarize_requests(result.after_reject_reload.requests)
    if result.after_accept.available:
        summary["after_accept"] = summarize_requests(result.after_accept.requests)
    result.network_summary = summary


def reject_tracking_evidence(result: "ConsentRuntimeResult") -> dict:
    """What was still tracked after Reject, right after the click and on the next page."""
    before_names = {(c.name, c.domain) for c in result.before_consent.consent_required_cookies}
    click = result.after_reject.tracker_requests if result.after_reject.available else []
    reload = result.after_reject_reload.tracker_requests if result.after_reject_reload.available else []
    caps = [c for c in (result.after_reject, result.after_reject_reload) if c.available]
    new_cookies = sorted({c.name for cap in caps for c in cap.consent_required_cookies
                          if (c.name, c.domain) not in before_names})
    reqs = click + reload
    return {
        "vendors": sorted({r.vendor or r.domain for r in reqs}),
        "requests": sorted({r.short() for r in reqs})[:10],
        "new_cookies": new_cookies,
        "on_next_page_only": bool(reload) and not click,
        "next_page_checked": result.after_reject_reload.available,
    }


def check_runtime_consent(
    result: ConsentRuntimeResult, page_url: str, include_pre_consent: bool = True,
) -> List[dict]:
    """Findings from the browser check; [] if it didn't run. include_pre_consent=False
    skips the before-consent finding when network.py already reported it.
    """
    if not result.available:
        return []

    findings: List[dict] = []

    if include_pre_consent and result.before_consent.available and result.before_consent.tracker_requests:
        reqs = result.before_consent.tracker_requests
        names = sorted({r.vendor or r.domain for r in reqs})
        findings.append(_finding(
            "critical", "runtime",
            "Tracking activity before consent (live browser)",
            f"{page_url}: {len(reqs)} analytics/advertising collection request(s) "
            f"({', '.join(names)}) were observed before Accept/Reject was clicked.",
            "Gate these vendors' collection behind an explicit consent signal.",
        ))

    if not result.banner_detected:
        return findings  # no banner: covered by banner.py

    if result.reject_clicked and result.reject_blocks_tracking is False:
        ev = reject_tracking_evidence(result)
        names, new_cookies = ev["vendors"], ev["new_cookies"]
        evidence = []
        if names:
            evidence.append(f"collection requests from {', '.join(names)}"
                            + (" (on the next page view)" if ev["on_next_page_only"] else ""))
        if new_cookies:
            evidence.append(f"new analytics/marketing cookies {', '.join(new_cookies[:5])}")
        findings.append(_finding(
            "critical", "runtime",
            "Reject does not stop tracking",
            f"{page_url}: after clicking '{result.reject_clicked_label}', "
            + ("; ".join(evidence) or "tracking activity") + " were still observed.",
            "Ensure the reject action actually disables analytics/marketing tags, not just the banner UI.",
        ))
    elif not result.reject_button_found:
        findings.append(_finding(
            "warning", "runtime",
            "No reject control found in the rendered consent banner",
            f"{page_url}: the rendered consent banner ({(result.banner or {}).get('container')}) was inventoried "
            "and no Reject / Necessary-only control was found on either layer.",
            "Offer a 'Reject all' or 'Necessary only' control in the banner.",
        ))

    if result.reject_layer == 2 and result.accept_button_found:
        findings.append(_finding(
            "warning", "runtime",
            "Reject is only available in the second layer",
            f"{page_url}: Accept is offered on the first banner layer, but rejecting requires opening "
            f"'{result.manage_clicked_label}' first.",
            "Put a 'Reject all' control on the first layer with the same prominence as 'Accept all'.",
        ))

    if result.accept_clicked and result.accept_allows_tracking is False:
        findings.append(_finding(
            "info", "runtime",
            "No tracking observed after Accept",
            f"{page_url}: after clicking '{result.accept_clicked_label}', no analytics/advertising collection "
            "request or new analytics/marketing cookie was observed within the test window.",
            "If the site uses analytics, verify tags fire after consent (check for JS errors).",
        ))
    elif not result.accept_button_found:
        findings.append(_finding(
            "warning", "runtime",
            "No accept control found in the rendered consent banner",
            f"{page_url}: the rendered consent banner was inventoried and no Accept control was found.",
            "Confirm the banner exposes a clearly labeled accept action.",
        ))

    # "Settings opened no panel" is reported by preferences.py.

    return findings


def _finding(severity: str, category: str, title: str, description: str, recommendation: str) -> dict:
    return {
        "module": MODULE,
        "category": category,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
