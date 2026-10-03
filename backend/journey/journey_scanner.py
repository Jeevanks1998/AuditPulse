"""
journey/journey_scanner.py

Scans the actual website and discovers what exists — pages, and every
interactive element on each rendered page. Nothing here knows any
website-specific button, label or journey: the rendered DOM is the source
of truth.

    start URL
       ↓  render in a real browser (JavaScript executed)
    discover elements (links, buttons, CTAs, forms + fields + submit,
    downloads, videos, search, navigation, phone/email links, tabs,
    accordions, modal triggers, any other clickable element)
       ↓
    follow same-site links (breadth-first) within the audit's crawl limits
       ↓
    pages + elements + forms + page relationships (parent → child)

Crawl limits and safety reuse the existing AuditPulse controls:
  * the audit's own max_pages and depth ("homepage" → the homepage plus the
    pages it links to directly; "full" → a deeper breadth-first walk)
  * robots.txt via crawler.robots.RobotsChecker, and its crawl-delay
  * same-site only; asset URLs (PDF, images…) are downloads, not pages
  * no form is ever submitted while scanning
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urldefrag, urlparse

from config.logging import logger
from config.browser import goto_page
from journey.browser_session import is_browser_dead_error
from crawler.links import ASSET_EXTENSIONS, NON_CRAWLABLE_SCHEMES

# Hard ceilings on top of the audit's own max_pages, so one audit can never
# turn into an unbounded browser crawl.
HOMEPAGE_DEPTH_PAGE_CAP = 8
FULL_DEPTH_PAGE_CAP = 25
FULL_DEPTH_LEVELS = 3
PAGE_SETTLE_MS = 1_200
MAX_HTML_BYTES = 4_000_000
MAX_ELEMENTS_PER_PAGE = 400
MAX_CRAWL_DELAY_S = 5.0

# Runs in the rendered page. Collects every interactive element and every
# form, tagging each element with data-journey-id so later steps can find
# exactly the same element again. No labels or site-specific names here —
# only DOM structure, roles and attributes.
DISCOVER_JS = r"""
(args) => {
  const { maxElements, idPrefix } = args;
  const CANDIDATES = [
    'a[href]', 'button', 'input[type=submit]', 'input[type=button]', 'input[type=image]', 'input[type=reset]',
    '[role=button]', '[role=link]', '[role=tab]', '[role=menuitem]', '[role=switch]', '[role=option]',
    'summary', '[aria-expanded]', '[aria-haspopup]', '[aria-controls]',
    '[onclick]', '[data-toggle]', '[data-bs-toggle]', '[data-target]', '[data-bs-target]',
    'video', 'audio', 'iframe[src]', 'select', 'input[type=search]', '[role=search] input', '[role=searchbox]',
    '[tabindex="0"]'
  ].join(',');

  const isVisible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0.05;
  };
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const textOf = (el) => clean(el.innerText || el.textContent || '').slice(0, 160);
  const accName = (el) => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map(id => document.getElementById(id)).filter(Boolean).map(textOf).join(' ');
      if (t) return clean(t).slice(0, 160);
    }
    const direct = el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt');
    if (direct) return clean(direct).slice(0, 160);
    if (el.id) {
      const lab = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (lab) return textOf(lab);
    }
    const img = el.querySelector && el.querySelector('img[alt]');
    const t = textOf(el) || (el.value || '') || (el.getAttribute('placeholder') || '') || (img ? img.getAttribute('alt') : '');
    return clean(t).slice(0, 160);
  };
  const cssPath = (el) => {
    if (el.id && /^[A-Za-z][\w-]*$/.test(el.id) && document.querySelectorAll('#' + el.id).length === 1) return '#' + el.id;
    const parts = [];
    let n = el;
    while (n && n.nodeType === 1 && n !== document.body && parts.length < 6) {
      let p = n.tagName.toLowerCase();
      const parent = n.parentElement;
      if (parent) {
        const same = [...parent.children].filter(c => c.tagName === n.tagName);
        if (same.length > 1) p += ':nth-of-type(' + (same.indexOf(n) + 1) + ')';
      }
      parts.unshift(p);
      n = parent;
    }
    return parts.join(' > ');
  };
  const landmark = (el) => {
    const lm = el.closest('nav, header, footer, main, aside, form, [role=navigation], [role=banner], [role=contentinfo], [role=main], [role=search], [role=dialog], dialog, [role=complementary]');
    if (!lm) return null;
    const role = lm.getAttribute('role');
    return role || lm.tagName.toLowerCase();
  };
  const headingContext = (el) => {
    let n = el;
    for (let i = 0; i < 6 && n; i++) {
      const h = n.querySelector && n.querySelector('h1,h2,h3');
      if (h && h !== el) return textOf(h).slice(0, 80);
      n = n.parentElement;
    }
    return null;
  };
  const attrs = (el) => {
    const keep = {};
    for (const a of el.attributes) {
      const k = a.name;
      if (k === 'style' || k.startsWith('on') && k !== 'onclick') continue;
      if (k === 'class' || k === 'id' || k === 'name' || k === 'type' || k === 'href' || k === 'download' ||
          k === 'target' || k === 'rel' || k === 'title' || k === 'alt' || k === 'action' || k === 'method' ||
          k === 'src' || k === 'role' || k === 'tabindex' || k === 'onclick' || k.startsWith('aria-') || k.startsWith('data-')) {
        keep[k] = (a.value || '').slice(0, 200);
      }
      if (Object.keys(keep).length >= 24) break;
    }
    return keep;
  };
  const styleSignals = (el) => {
    const cs = getComputedStyle(el);
    const bg = cs.backgroundColor;
    const hasBg = bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent';
    const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    return {
      has_background: !!hasBg, padded: pad >= 12, bold: parseInt(cs.fontWeight, 10) >= 600,
      border_radius: parseFloat(cs.borderTopLeftRadius) || 0, cursor: cs.cursor,
      font_size: parseFloat(cs.fontSize) || 0,
    };
  };
  const signature = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'a|' + (el.getAttribute('href') || '');
    if (tag === 'form') return 'form|' + (el.getAttribute('action') || '') + '|' + (el.getAttribute('id') || '');
    if (tag === 'iframe' || tag === 'video' || tag === 'audio') return tag + '|' + (el.getAttribute('src') || '');
    return tag + '|' + textOf(el).toLowerCase().slice(0, 60);
  };

  window.__apJourneySeq = window.__apJourneySeq || 0;
  const tag = (el) => {
    let id = el.getAttribute('data-journey-id');
    if (!id) { id = idPrefix + (++window.__apJourneySeq); el.setAttribute('data-journey-id', id); }
    return id;
  };

  // Cookie / consent banners (CMPs). Their buttons are tested by the Consent
  // module; clicking them here would change consent mid-journey.
  const CMP_SEL = [
    '#onetrust-consent-sdk', '#onetrust-banner-sdk', '#onetrust-pc-sdk', '.ot-sdk-container', '.optanon-alert-box-wrapper',
    '#CybotCookiebotDialog', '#didomi-host', '.didomi-popup-container', '#usercentrics-root', '#uc-banner',
    '.qc-cmp2-container', '#qc-cmp2-ui', '#truste-consent-track', '#consent_blackbar', '.truste_box_overlay',
    '#axeptio_overlay', '#tarteaucitronRoot', '.osano-cm-window', '#cmpbox', '#cmpwrapper', '.cc-window',
    '#cookie-law-info-bar', '#cookiescript_injected', '#iubenda-cs-banner', '#termly-code-snippet-support',
    '#sp_message_container', '[id^="sp_message_container"]', '.fc-consent-root', '#gdpr-consent-tool-wrapper',
    '[id*="cookie-banner" i]', '[class*="cookie-banner" i]', '[id*="cookie-consent" i]', '[class*="cookie-consent" i]',
    '[id*="consent-banner" i]', '[class*="consent-banner" i]', '[id*="cookie-notice" i]', '[class*="cookie-notice" i]',
    '[role=dialog][aria-label*="cookie" i]', '[role=dialog][aria-label*="consent" i]', '[role=dialog][aria-label*="privacy" i]',
  ].join(',');
  const inConsent = (el) => { try { return !!el.closest(CMP_SEL); } catch (e) { return false; } };

  const seen = new Set();
  const out = [];
  const nodes = [...document.querySelectorAll(CANDIDATES)];
  for (const el of nodes) {
    if (out.length >= maxElements) break;
    if (seen.has(el)) continue;
    // A clickable nested inside another clickable (icon inside a link) is the same interaction.
    const outer = el.parentElement && el.parentElement.closest('a[href], button, [role=button], summary');
    if (outer && nodes.includes(outer) && outer !== el) continue;
    seen.add(el);
    const tagName = el.tagName.toLowerCase();
    // [tabindex=0] only counts if it looks clickable.
    if (el.matches('[tabindex="0"]') && !el.matches('a,button,input,select,summary,[role],[onclick]') &&
        getComputedStyle(el).cursor !== 'pointer') continue;
    const r = el.getBoundingClientRect();
    const formEl = el.closest('form');
    let dest = null;
    if (tagName === 'a') dest = el.href || null;
    else if (tagName === 'iframe' || tagName === 'video' || tagName === 'audio') dest = el.currentSrc || el.src || null;
    else if (formEl && (el.type === 'submit' || (tagName === 'button' && (!el.getAttribute('type') || el.type === 'submit')))) dest = formEl.action || null;
    out.push({
      id: tag(el), tag: tagName, role: el.getAttribute('role'), type: el.getAttribute('type'),
      text: textOf(el), accessible_name: accName(el),
      aria: Object.fromEntries([...el.attributes].filter(a => a.name.startsWith('aria-')).map(a => [a.name, a.value.slice(0, 120)])),
      attributes: attrs(el), destination: dest,
      position: { x: Math.round(r.left + scrollX), y: Math.round(r.top + scrollY), width: Math.round(r.width), height: Math.round(r.height) },
      selector: cssPath(el), visible: isVisible(el), landmark: landmark(el), heading: headingContext(el),
      form_id: formEl ? tag(formEl) : null, style: styleSignals(el), signature: signature(el),
      in_dialog: !!el.closest('[role=dialog], dialog, [aria-modal=true]'),
      in_consent: inConsent(el),
    });
  }

  const forms = [...document.querySelectorAll('form')].slice(0, 30).map((f) => {
    const r = f.getBoundingClientRect();
    const fields = [...f.querySelectorAll('input, select, textarea')].map((i) => {
      const t = (i.getAttribute('type') || i.tagName.toLowerCase()).toLowerCase();
      return {
        tag: i.tagName.toLowerCase(), type: t, name: i.getAttribute('name'), id: i.id || null,
        label: accName(i) || i.getAttribute('placeholder') || i.getAttribute('name') || '',
        required: i.required || i.getAttribute('aria-required') === 'true',
        visible: t !== 'hidden' && isVisible(i), autocomplete: i.getAttribute('autocomplete'),
        pattern: i.getAttribute('pattern'), journey_id: tag(i),
      };
    });
    const submits = [...f.querySelectorAll('button, input[type=submit], input[type=image]')]
      .filter(b => b.tagName.toLowerCase() !== 'button' || !b.getAttribute('type') || b.type === 'submit')
      .map(b => ({ text: accName(b), journey_id: tag(b) }));
    const onsubmit = (f.getAttribute('onsubmit') || '');
    const trackingAttrs = [...f.attributes].filter(a => /track|analytic|gtm|ga4|datalayer|event/i.test(a.name + a.value)).map(a => a.name);
    return {
      id: tag(f), name: f.getAttribute('name') || f.id || null, action: f.action || null,
      method: (f.getAttribute('method') || 'get').toLowerCase(), novalidate: f.noValidate,
      position: { x: Math.round(r.left + scrollX), y: Math.round(r.top + scrollY), width: Math.round(r.width), height: Math.round(r.height) },
      visible: isVisible(f), landmark: landmark(f), heading: headingContext(f), role: f.getAttribute('role'),
      selector: cssPath(f), fields, submits,
      tracking_hints: trackingAttrs.concat(/dataLayer|gtag|ga\(|_paq|utag|analytics/i.test(onsubmit) ? ['onsubmit'] : []),
      signature: signature(f), in_consent: inConsent(f),
    };
  });
  return { elements: out, forms, title: document.title, lang: document.documentElement.lang || null,
           final_url: location.href, doc_height: document.documentElement.scrollHeight };
}
"""


@dataclass
class DiscoveredElement:
    id: str
    page_url: str
    tag: str
    text: str = ""
    accessible_name: str = ""
    role: Optional[str] = None
    type: Optional[str] = None
    aria: Dict[str, str] = field(default_factory=dict)
    attributes: Dict[str, str] = field(default_factory=dict)
    destination: Optional[str] = None
    position: Dict[str, int] = field(default_factory=dict)
    selector: str = ""
    visible: bool = False
    landmark: Optional[str] = None
    heading: Optional[str] = None
    form_id: Optional[str] = None
    style: Dict[str, object] = field(default_factory=dict)
    signature: str = ""
    in_dialog: bool = False
    in_consent: bool = False   # inside a cookie / consent banner (tested by the Consent module)
    dynamic: bool = False      # not present in the server-delivered HTML

    @property
    def label(self) -> str:
        return self.accessible_name or self.text or self.attributes.get("title") or self.tag


@dataclass
class DiscoveredForm:
    id: str
    page_url: str
    name: Optional[str] = None
    action: Optional[str] = None
    method: str = "get"
    novalidate: bool = False
    position: Dict[str, int] = field(default_factory=dict)
    visible: bool = False
    landmark: Optional[str] = None
    heading: Optional[str] = None
    role: Optional[str] = None
    selector: str = ""
    fields: List[dict] = field(default_factory=list)
    submits: List[dict] = field(default_factory=list)
    tracking_hints: List[str] = field(default_factory=list)
    signature: str = ""
    in_consent: bool = False
    dynamic: bool = False


@dataclass
class PageScan:
    url: str
    title: str = ""
    depth: int = 0
    parent_url: Optional[str] = None
    via_label: Optional[str] = None       # the discovered link that led here
    via_element_id: Optional[str] = None
    status: Optional[int] = None
    final_url: Optional[str] = None
    error: Optional[str] = None
    element_count: int = 0
    form_count: int = 0
    links_out: List[str] = field(default_factory=list)
    lang: Optional[str] = None
    analytics_on_load: List[str] = field(default_factory=list)   # vendor:event seen while this page loaded
    screenshot: Optional[str] = None


@dataclass
class ScanResult:
    start_url: str
    pages: List[PageScan] = field(default_factory=list)
    elements: List[DiscoveredElement] = field(default_factory=list)
    forms: List[DiscoveredForm] = field(default_factory=list)
    skipped_by_robots: List[str] = field(default_factory=list)
    page_limit: int = 0
    stopped_early: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return p._replace(path=path, params="").geturl()


def _same_site(url: str, host: str) -> bool:
    h = (urlparse(url).hostname or "").lower()
    host = host.lower()
    strip = lambda x: x[4:] if x.startswith("www.") else x  # noqa: E731
    return strip(h) == strip(host)


def is_asset_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    ext = path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    return bool(ext) and (ext in ASSET_EXTENSIONS or f".{ext}" in ASSET_EXTENSIONS)


# URLs that can change state on a plain GET (add-to-cart links, sign-out,
# delete/unsubscribe endpoints…) are never *crawled*; the links themselves are
# still discovered and reported.
_STATEFUL_URL_RE = re.compile(
    r"(add[-_]?to[-_]?(cart|basket|bag)|/cart\b|/basket\b|/checkout|/payment|/pay\b|log[-_]?out|sign[-_]?out|"
    r"/delete|/remove|unsubscribe|/order/confirm)", re.I)


def is_stateful_url(url: str) -> bool:
    p = urlparse(url)
    return bool(_STATEFUL_URL_RE.search(f"{p.path}?{p.query}"))


def _crawlable(url: str, host: str) -> bool:
    p = urlparse(url)
    if p.scheme in NON_CRAWLABLE_SCHEMES or p.scheme not in ("http", "https"):
        return False
    return _same_site(url, host) and not is_asset_url(url) and not is_stateful_url(url)


def page_limit_for(depth: str, max_pages: int) -> Tuple[int, int]:
    """(page cap, link levels) for an audit's depth setting and max_pages."""
    if depth == "full":
        return max(1, min(max_pages, FULL_DEPTH_PAGE_CAP)), FULL_DEPTH_LEVELS
    return max(1, min(max_pages, HOMEPAGE_DEPTH_PAGE_CAP)), 1


def _static_signatures(html: str) -> Set[str]:
    """Signatures of the elements present in the server-delivered HTML."""
    from bs4 import BeautifulSoup

    sigs: Set[str] = set()
    soup = BeautifulSoup(html or "", "lxml")
    for a in soup.find_all("a", href=True):
        sigs.add("a|" + a.get("href", ""))
    for f in soup.find_all("form"):
        sigs.add("form|" + (f.get("action") or "") + "|" + (f.get("id") or ""))
    for t in soup.find_all(["iframe", "video", "audio"]):
        sigs.add(f"{t.name}|" + (t.get("src") or ""))
    for t in soup.find_all(["button", "summary", "input", "select"]):
        text = re.sub(r"\s+", " ", t.get_text(" ", strip=True) or t.get("value") or "").strip().lower()[:60]
        sigs.add(f"{t.name}|{text}")
    for t in soup.find_all(attrs={"role": True}):
        text = re.sub(r"\s+", " ", t.get_text(" ", strip=True)).strip().lower()[:60]
        sigs.add(f"{t.name}|{text}")
    return sigs


async def http_fetch(context, url: str, method: str = "GET", timeout: float = 15.0):
    """
    Plain HTTP request carrying the browser context's cookies (so consent /
    session state matches the rendered page). Returns (status, headers, text)
    or (None, {}, "") on failure. Used for the server-HTML snapshot and for
    download / external-link checks — never for form submission.
    """
    import httpx

    from crawler.robots import DEFAULT_USER_AGENT

    try:
        jar = {c["name"]: c["value"] for c in await context.cookies(url)}
    except Exception:  # noqa: BLE001
        jar = {}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, cookies=jar,
                                     headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
            if method == "HEAD":
                r = await client.request("HEAD", url)
                if r.status_code < 400 and r.status_code != 405:
                    return r.status_code, dict(r.headers), ""
            # Streamed GET: only text/HTML bodies are read (capped), so a
            # 50 MB PDF behind a download link is never held in memory.
            async with client.stream("GET", url) as r:
                text = ""
                if method == "GET" and "text" in r.headers.get("content-type", ""):
                    chunks, size = [], 0
                    async for chunk in r.aiter_bytes():
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > MAX_HTML_BYTES:
                            break
                    text = b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
                return r.status_code, dict(r.headers), text
    except Exception as exc:  # noqa: BLE001
        logger.info(f"journey: HTTP {method} {url} failed: {exc}")
        return None, {}, ""


# Recycle the tab every N pages: one long-lived tab keeps every visited
# page's JS heap / caches alive, which on a small container ends with
# Chromium being killed for memory.
RECYCLE_TAB_EVERY = 4


async def discover_page(page, page_url: str, id_prefix: str) -> dict:
    return await page.evaluate(DISCOVER_JS, {"maxElements": MAX_ELEMENTS_PER_PAGE, "idPrefix": id_prefix})


async def scan_site(
    session,
    start_url: str,
    max_pages: int,
    depth: str,
    on_page_loaded=None,
    on_page_scanned=None,
    capture=None,
    deadline: Optional[float] = None,
) -> ScanResult:
    """
    Breadth-first scan of the rendered site in an existing browser context
    (journey/__init__ opens it through analytics.runtime.open_runtime_browser).
    `on_page_loaded(page, url)` runs after the first page renders (used to
    handle the consent banner once, before discovery). `on_page_scanned(page,
    scan)` runs after each page is discovered (page screenshot). `capture`
    (journey_tracking.TrackingCapture) attributes analytics hits to page loads.
    """
    import httpx

    from crawler.robots import DEFAULT_USER_AGENT, RobotsChecker

    host = urlparse(start_url).hostname or ""
    limit, levels = page_limit_for(depth, max_pages)
    result = ScanResult(start_url=start_url, page_limit=limit)

    queue: List[Tuple[str, int, Optional[str], Optional[str], Optional[str]]] = [
        (normalize_url(start_url), 0, None, None, None)]
    queued: Set[str] = {normalize_url(start_url)}
    robots = RobotsChecker()
    crawl_delay = 0.0

    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0, headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        try:
            crawl_delay = min(float(await robots.crawl_delay(client, start_url) or 0.0), MAX_CRAWL_DELAY_S)
        except Exception:  # noqa: BLE001
            crawl_delay = 0.0

        # `session` is a journey.browser_session.JourneyBrowser (relaunches a
        # killed Chromium) — or, for older callers, a plain BrowserContext.
        restartable = hasattr(session, "restart")

        def _ctx():
            return session.context if restartable else session

        async def _new_page():
            return await (session.new_page() if restartable else session.new_page())

        page = await _new_page()
        first = True
        pages_on_tab = 0
        while queue and len(result.pages) < limit:
            if deadline is not None and time.monotonic() > deadline:
                logger.info(f"journey: scan time budget reached after {len(result.pages)} page(s)")
                result.stopped_early = True
                break
            if pages_on_tab >= RECYCLE_TAB_EVERY or page.is_closed():
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass
                if restartable:
                    await session.save_state()
                page = await _new_page()
                pages_on_tab = 0
            url, level, parent, via_label, via_id = queue.pop(0)
            try:
                allowed = await robots.can_fetch(client, url)
            except Exception:  # noqa: BLE001 — unreachable robots.txt never blocks the scan
                allowed = True
            if not allowed:
                result.skipped_by_robots.append(url)
                continue

            scan = PageScan(url=url, depth=level, parent_url=parent, via_label=via_label, via_element_id=via_id)
            result.pages.append(scan)
            load_mark = capture.mark() if capture is not None else None
            pages_on_tab += 1
            try:
                try:
                    resp = await goto_page(page, url)
                except Exception as nav_exc:  # noqa: BLE001
                    # Chromium was killed (memory): relaunch and retry this page once.
                    if not (restartable and is_browser_dead_error(nav_exc) and await session.restart(str(nav_exc))):
                        raise
                    page = await _new_page()
                    pages_on_tab = 1
                    resp = await goto_page(page, url)
                scan.status = resp.status if resp else None
                await page.wait_for_timeout(PAGE_SETTLE_MS)
                if first and on_page_loaded is not None:
                    await on_page_loaded(page, url)
                    first = False
                # Server-delivered HTML (same cookies as the browser) — anything
                # rendered that isn't in it was generated dynamically.
                _status, _headers, static_html = await http_fetch(_ctx(), url)
                static_sigs = _static_signatures(static_html) if static_html else set()

                data = await discover_page(page, url, f"p{len(result.pages)}e")
                scan.title = data.get("title") or ""
                scan.final_url = data.get("final_url")
                scan.lang = data.get("lang")
                for raw in data.get("elements", []):
                    el = DiscoveredElement(page_url=url, **{k: v for k, v in raw.items()
                                                             if k in DiscoveredElement.__dataclass_fields__})
                    el.dynamic = bool(static_sigs) and el.signature not in static_sigs
                    result.elements.append(el)
                for raw in data.get("forms", []):
                    f = DiscoveredForm(page_url=url, **{k: v for k, v in raw.items()
                                                       if k in DiscoveredForm.__dataclass_fields__})
                    f.dynamic = bool(static_sigs) and f.signature not in static_sigs
                    result.forms.append(f)
                scan.element_count = len(data.get("elements", []))
                scan.form_count = len(data.get("forms", []))

                # Follow same-site links discovered on this page.
                outs: List[str] = []
                for raw in data.get("elements", []):
                    dest = raw.get("destination")
                    if raw.get("tag") != "a" or not dest:
                        continue
                    nd = normalize_url(urljoin(url, dest))
                    if not _crawlable(nd, host):
                        continue
                    if nd not in outs:
                        outs.append(nd)
                    if level < levels and nd not in queued and len(queued) < limit * 4:
                        queued.add(nd)
                        label = (raw.get("accessible_name") or raw.get("text") or "")[:80]
                        queue.append((nd, level + 1, url, label, raw.get("id")))
                scan.links_out = outs[:200]
                if capture is not None:
                    scan.analytics_on_load = sorted({f"{e.vendor}:{e.event}" for e in capture.between(load_mark)
                                                     if e.event})[:20]
                if on_page_scanned is not None:
                    await on_page_scanned(page, scan)
            except Exception as exc:  # noqa: BLE001 — one bad page never stops the scan
                scan.error = str(exc)[:300]
                logger.info(f"journey: could not scan {url}: {exc}")
            if crawl_delay:
                await asyncio.sleep(crawl_delay)
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass
    return result
