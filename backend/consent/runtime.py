"""
consent/runtime.py

The live *behavioral* half of consent/: loads the site in a real
browser, finds the rendered consent banner, inventories its controls,
clicks them, and re-observes cookies + network traffic afterwards.

Flow (banner-first, evidence-based):

    detect banner
          ↓
    locate banner/container (CMP selector, ARIA dialog, CMP iframe, or
    the smallest element that talks about cookies/consent and holds a
    consent control — searched across iframes and open shadow roots)
          ↓
    find controls inside that container only
          ↓
    build the control inventory   ← single source of truth:
        banner_detected
        controls:
          - label     (exact visible text)
          - action    (accept_all / reject_non_essential / …)
          - selector
          - frame
          - visible
          - clickable
          ↓
    click only detected controls

Unlike the old version, nothing is found by regex-matching every link
and button on the page: an unrelated "Continue" button, a "Settings"
nav link or an "OK" in a newsletter popup can no longer be clicked as
Accept/Manage/Reject.

Three clean browser contexts are used so no leg contaminates another:

    reject leg   — before-consent capture, initial screenshot, click
                   Reject (first layer; if absent, open Manage and look
                   for Reject on the second layer), capture after
    accept leg   — fresh context, click Accept, capture after
    manage leg   — fresh context, click Manage/Personalize, inventory the
                   preference panel (skipped if the reject leg already
                   opened it)

Same degrade-gracefully contract as the rest of consent/: any Playwright
failure yields available=False / <state>.available=False on the affected
leg rather than raising, and a leg that couldn't run is "not tested",
never a pass.
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

MODULE = "consent"
CATEGORY = "runtime"

SETTLE_MS = 1_500          # idle window after page load to catch deferred trackers
CLICK_SETTLE_MS = 2_500    # idle window after a button click to catch anything it triggers
BANNER_RENDER_MS = 1_500   # minimum wait for a client-side-rendered banner
BANNER_MAX_WAIT_MS = 8_000  # keep polling for a late CMP up to this long
BANNER_POLL_MS = 500

# Known CMP iframe hosts: if a frame comes from one of these, its whole
# document is the consent UI (Sourcepoint, TrustArc, Quantcast, Funding Choices…).
_CMP_FRAME_HOSTS = (
    "privacy-mgmt.com", "sourcepoint.com", "consent.trustarc.com", "trustarc.com",
    "consensu.org", "quantcast.com", "fundingchoicesmessages.google.com", "cookiebot.com",
    "consentmanager.net", "usercentrics.eu", "privacy-center.org", "onetrust.com", "cookielaw.org",
)

CONTAINER_HANDLE = "__container__"

_VIA_SCORE = {"cmp_selector": 6, "cmp_iframe": 5, "aria_dialog": 4, "text_heuristic": 0}

# Runs inside each frame. Finds candidate consent containers and the
# clickable controls inside each one, tagging every control with a
# data-auditpulse-ctl attribute so Python can click exactly that element.
# Open shadow roots are traversed (Usercentrics and others render there).
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
    category: str  # cookies.categories.{ESSENTIAL,FUNCTIONAL,ANALYTICS,MARKETING,CONSENT_MANAGEMENT,UNKNOWN}
    purpose: str = "unknown"
    vendor: Optional[str] = None


@dataclass
class ConsentStateCapture:
    """Everything observed at one point in the runtime flow (before / after-reject / after-accept)."""

    available: bool = False
    cookies: List[CookieSnapshot] = field(default_factory=list)
    requests: List[NetworkRequest] = field(default_factory=list)
    error: Optional[str] = None
    # localStorage / sessionStorage keys at capture time (evidence that the
    # context started empty and what the page/CMP wrote).
    local_storage_keys: List[str] = field(default_factory=list)
    session_storage_keys: List[str] = field(default_factory=list)

    @property
    def tracker_requests(self) -> List[NetworkRequest]:
        """Confirmed tracking activity only (analytics/advertising collection hits)."""
        return [r for r in self.requests if r.is_tracking]

    @property
    def vendor_requests(self) -> List[NetworkRequest]:
        """Any request to a recognized analytics/advertising/tag-manager vendor (loaders included)."""
        return [r for r in self.requests if r.tracker_name]

    @property
    def consent_required_cookies(self) -> List[CookieSnapshot]:
        """Analytics + marketing cookies — the only ones whose presence is evidence of a failure."""
        return [c for c in self.cookies if requires_consent(c.category)]

    @property
    def non_essential_cookies(self) -> List[CookieSnapshot]:
        """Back-compat alias. Unknown / consent-management / functional cookies are NOT included."""
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
    """The rendered consent banner and its controls — consent buttons' single source of truth."""
    banner_detected: bool = False
    detected_via: Optional[str] = None   # cmp_selector | aria_dialog | cmp_iframe | text_heuristic
    container: Optional[str] = None       # selector / id / class of the container
    frame: str = "main"
    text_excerpt: str = ""
    is_overlay: bool = False              # position fixed/sticky
    toggle_count: int = 0                 # category checkboxes/switches inside
    controls: List[ConsentControl] = field(default_factory=list)
    # Selector that re-locates exactly the detected container element (used to
    # clip screenshots to the real banner, CMP-agnostic). Not serialized.
    element_selector: Optional[str] = None

    def first(self, order) -> Optional[ConsentControl]:
        """First control matching the action preference order, visible/clickable ones first."""
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

    # The rendered-banner inventory (first layer) and, when the preference
    # panel was opened, its controls (layer 2). These are the single source
    # of truth for every flag below.
    banner: Optional[dict] = None
    controls: List[ConsentControl] = field(default_factory=list)
    preference_panel: Optional[dict] = None
    preference_controls: List[ConsentControl] = field(default_factory=list)

    accept_button_found: bool = False
    reject_button_found: bool = False      # on any layer — see reject_layer
    manage_button_found: bool = False
    reject_layer: Optional[int] = None     # 1 = first banner layer, 2 = only in the preference panel

    # Authoritative "the live browser saw a consent banner" signal. False
    # means "not seen" — including when the pass didn't run — and must
    # never be used to *disprove* a banner the static scan found.
    banner_detected: bool = False

    accept_clicked: bool = False
    reject_clicked: bool = False
    manage_clicked: bool = False
    accept_clicked_label: Optional[str] = None
    reject_clicked_label: Optional[str] = None
    manage_clicked_label: Optional[str] = None

    before_consent: ConsentStateCapture = field(default_factory=ConsentStateCapture)
    after_reject: ConsentStateCapture = field(default_factory=ConsentStateCapture)
    # Leg 2's own initial state (fresh context, before Accept) — the
    # baseline the after-accept capture is compared against.
    before_accept: ConsentStateCapture = field(default_factory=ConsentStateCapture)
    after_accept: ConsentStateCapture = field(default_factory=ConsentStateCapture)

    # Fresh-scan bookkeeping: unique per run, used in screenshot filenames
    # so no earlier scan's evidence is ever reused or overwritten.
    scan_id: Optional[str] = None
    fresh_contexts: int = 0
    leg_log: List[str] = field(default_factory=list)

    initial_banner_screenshot: Optional[str] = None
    preferences_screenshot: Optional[str] = None
    reject_screenshot: Optional[str] = None
    accept_screenshot: Optional[str] = None

    # Verdicts — None means "not tested" and must never be treated as a pass.
    reject_blocks_tracking: Optional[bool] = None
    accept_allows_tracking: Optional[bool] = None
    personalize_exposes_controls: Optional[bool] = None

    # JSON-friendly per-category request summaries for the report.
    network_summary: Dict[str, dict] = field(default_factory=dict)

    tested_at: Optional[str] = None

    def buttons_detection(self) -> ButtonsDetection:
        """The rendered inventory expressed as a ButtonsDetection (source='runtime')."""
        banner = self.banner or {}
        return ButtonsDetection.from_controls(
            self.controls + self.preference_controls,
            container_found=self.banner_detected,
            container_hint=banner.get("container"),
            detected_via=banner.get("detected_via"),
            source="runtime",
        )


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def _is_cmp_frame(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _CMP_FRAME_HOSTS)


async def inventory_banner(
    page, layer: int = 1, avoid_container: Optional[str] = None,
) -> Tuple[BannerInventory, Dict[str, object]]:
    """
    Scans every frame of `page` for a consent container and returns
    (inventory, handles) where handles maps a control's selector to the
    frame it lives in, so `_click_control` can click exactly that element.
    """
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
            # A text-heuristic container must actually hold an accept/reject
            # control; selector/dialog/CMP-iframe containers are banners on
            # their own merit even if their wording isn't recognized.
            if via == "text_heuristic" and not (n_accept or n_reject):
                continue
            if via != "text_heuristic" and not (n_accept or n_reject or n_manage) and not cand.get("controls"):
                continue
            score = (n_accept + n_reject) * 10 + n_manage * 3 + _VIA_SCORE.get(via, 0) \
                + (2 if cand.get("fixed") else 0) - min(cand.get("textLen", 0), 4000) // 1000
            frame_label = "main" if frame is main else frame_url
            if layer == 2:
                # Preference panel: favour the container that exposes category
                # toggles, and the one that is *not* the first-layer banner.
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
    """Polls for a (possibly late, client-rendered) banner up to BANNER_MAX_WAIT_MS."""
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
    """Clicks exactly the inventoried control. Re-inventories once if the DOM re-rendered."""
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


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------

async def run_consent_runtime(url: str, scan_id: Optional[str] = None) -> ConsentRuntimeResult:
    """
    A fresh, dynamic consent scan. Nothing is reused from any earlier scan:
    every leg opens a brand-new browser context (no cookies, no local/session
    storage, no cache, no service workers), records its own network traffic,
    re-detects the banner and re-builds the control inventory, and writes
    screenshots under this run's unique `scan_id`.

        Leg 1  fresh context → load → wait for banner → detect banner →
               screenshot → cookies → network → detect controls →
               Manage/Personalize if present → verify panel → screenshot →
               Reject if present → cookies/network → screenshot
        Leg 2  fresh context → load → initial state → detect Accept →
               click the detected Accept → cookies/network → screenshot

    Nothing is assumed to exist: if the banner only offers "Continue without
    accepting", that control is recorded (action reject_non_essential) and
    used as the reject action; a missing Accept is reported, not invented.
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
                    await _run_leg_two(browser, url, hostname, result)
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
    """A brand-new, isolated context: empty cookie jar, storage and cache."""
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


async def _open_preferences(page, handles, inv: BannerInventory, result: ConsentRuntimeResult, url: str):
    """Click the detected Manage/Personalize control and verify a preference panel actually appeared."""
    manage = inv.first(tuple(MANAGE_ACTIONS))
    if manage is None:
        return None, {}
    if not await _click_control(page, handles, manage):
        result.leg_log.append(f"leg 1: could not click '{manage.label}'")
        return None, {}
    await page.wait_for_timeout(CLICK_SETTLE_MS)
    result.manage_clicked = True
    result.manage_clicked_label = manage.label
    panel, panel_handles = await inventory_banner(page, layer=2, avoid_container=inv.container)
    if (panel.banner_detected and panel.container == inv.container and panel.frame == inv.frame
            and panel.toggle_count == 0
            and [(c.label, c.action) for c in panel.controls] == [(c.label, c.action) for c in inv.controls]):
        # Same banner, unchanged, no category toggles: the click opened nothing.
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
        f"leg 1: clicked '{manage.label}' → preference panel "
        + ("appeared" if result.personalize_exposes_controls else "did not appear"))
    return panel, panel_handles


async def _run_leg_one(browser, url: str, hostname: str, result: ConsentRuntimeResult) -> None:
    context = await _fresh_context(browser, result)
    try:
        page = await context.new_page()
        sink: List[NetworkRequest] = []
        page.on("request", lambda r: sink.append(_classify(r.url, r.resource_type, hostname)))

        await page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
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

        # Manage / Personalize first, if the banner offers it.
        panel, panel_handles = await _open_preferences(page, handles, inv, result, url)

        # Reject: prefer the reject control that is on screen now (preference
        # panel if it opened, otherwise the first layer); never invent one.
        reject, reject_handles, layer = None, handles, 1
        if panel is not None and panel.banner_detected:
            reject = panel.first(REJECT_CLICK_ORDER)
            reject_handles, layer = panel_handles, 2
        if reject is None:
            current, current_handles = await inventory_banner(page)
            reject = current.first(REJECT_CLICK_ORDER) if current.banner_detected else None
            reject_handles, layer = current_handles, 1
        if reject is None and first_layer_reject is not None and result.manage_clicked:
            # The panel replaced the first layer and offers no reject: reload in
            # the *same* leg is not clean, so record it as not reachable here.
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
    finally:
        await context.close()


async def _run_leg_two(browser, url: str, hostname: str, result: ConsentRuntimeResult) -> None:
    context = await _fresh_context(browser, result)
    try:
        page = await context.new_page()
        sink: List[NetworkRequest] = []
        page.on("request", lambda r: sink.append(_classify(r.url, r.resource_type, hostname)))
        await page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
        inv, handles = await _wait_for_banner(page)
        _record_inventory(result, inv)
        result.before_accept = await _state(context, page, sink)

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
    finally:
        await context.close()


async def _state(context, page, requests: List[NetworkRequest]) -> ConsentStateCapture:
    local_keys, session_keys = [], []
    try:
        keys = await page.evaluate(
            "() => { try { return [Object.keys(localStorage), Object.keys(sessionStorage)]; }"
            " catch (e) { return [[], []]; } }")
        local_keys, session_keys = keys[0][:50], keys[1][:50]
    except Exception:  # noqa: BLE001
        pass
    return ConsentStateCapture(
        available=True,
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
        out.append(CookieSnapshot(name=c["name"], domain=c.get("domain", ""), category=cls.category,
                                  purpose=cls.purpose, vendor=cls.vendor))
    return out


async def _capture(page, url: str, hint: str, scan_id: Optional[str] = None, element=None) -> Optional[str]:
    """Screenshot via consent.screenshots — clipped to the detected banner element when given."""
    return await capture_page_or_element(page, url, hint, scan_id=scan_id, element=element)


def _derive_verdicts(result: ConsentRuntimeResult) -> None:
    """
    Translates the raw captures into verdicts. Left as None ("not tested")
    whenever the underlying leg never ran.
    """
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
        new_cookies = [c for c in result.after_reject.consent_required_cookies
                       if (c.name, c.domain) not in before_names]
        result.reject_blocks_tracking = (
            len(result.after_reject.tracker_requests) == 0 and not new_cookies
        )

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
    if result.after_accept.available:
        summary["after_accept"] = summarize_requests(result.after_accept.requests)
    result.network_summary = summary


def check_runtime_consent(
    result: ConsentRuntimeResult, page_url: str, include_pre_consent: bool = True,
) -> List[dict]:
    """
    Findings from an already-run ConsentRuntimeResult. Empty list when
    runtime data wasn't available. `include_pre_consent=False` skips the
    before-consent tracking finding when consent.network already reported
    the same evidence (avoids counting it twice in the score).
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
        return findings  # banner.py's own finding covers "no banner"; nothing to click-test

    if result.reject_clicked and result.reject_blocks_tracking is False:
        after = result.after_reject
        names = sorted({r.vendor or r.domain for r in after.tracker_requests})
        before_names = {(c.name, c.domain) for c in result.before_consent.consent_required_cookies}
        new_cookies = sorted({c.name for c in after.consent_required_cookies if (c.name, c.domain) not in before_names})
        evidence = []
        if names:
            evidence.append(f"collection requests from {', '.join(names)}")
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

    # "Manage clicked but no panel appeared" is reported by consent.preferences
    # (static detection + runtime verification), not duplicated here.

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
