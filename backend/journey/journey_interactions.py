"""
journey/journey_interactions.py

Understands what each discovered element does, then safely tests the
important ones:

    element → what type?            (classify)
            → can it be interacted with safely?
            → where does it go?
            → what happens after interaction?   (InteractionTester)

Classification is multi-signal — never "if button text == X". Signals:
  * structure     tag, role, input type, aria-* (aria-haspopup, aria-expanded,
                  aria-controls, aria-selected), <summary>, data-toggle
  * destination   URL scheme (tel:, mailto:), file extension, download
                  attribute, same-site vs external, path segments
  * context       landmark (nav/header/footer/main/form/search/dialog),
                  enclosing form + whether the control submits it
  * presentation  button-like styling (background, padding, weight, radius),
                  size, cursor
  * intent words  a small generic multilingual vocabulary describing
                  *kinds* of actions (sign in, register, checkout, book…),
                  matched against the destination path and the accessible
                  name together. It describes action types, not any site's
                  buttons; every match is reported as a signal.

Production safety: nothing irreversible is ever executed. Form submissions,
purchases, payments, bookings, sign-out and delete/unsubscribe-type actions
are discovered, screenshotted and highlighted but never clicked. External
links are checked with an HTTP request instead of leaving the site.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from config.logging import logger
from journey.journey_scanner import DISCOVER_JS, DiscoveredElement, DiscoveredForm, normalize_url

# ---- classifications (requirement §3) ---------------------------------------
NAVIGATION = "navigation"
CTA = "cta"
FORM = "form"
FORM_START = "form_start"
FORM_SUBMIT = "form_submit"
DOWNLOAD = "download"
VIDEO = "video"
SEARCH = "search"
LOGIN = "login"
SIGNUP = "signup"
PURCHASE = "purchase"
APPOINTMENT = "appointment"
PHONE = "phone"
EMAIL = "email"
OTHER = "other"

CLASS_LABELS = {
    NAVIGATION: "Navigation", CTA: "CTA", FORM: "Form", FORM_START: "Form Start", FORM_SUBMIT: "Form Submit",
    DOWNLOAD: "Download", VIDEO: "Video", SEARCH: "Search", LOGIN: "Login", SIGNUP: "Signup",
    PURCHASE: "Purchase", APPOINTMENT: "Appointment", PHONE: "Phone", EMAIL: "Email", OTHER: "Other",
}

# UI pattern (how it behaves), orthogonal to the classification (what it is for).
PATTERN_LINK, PATTERN_BUTTON, PATTERN_TAB, PATTERN_ACCORDION, PATTERN_MODAL, PATTERN_MENU, PATTERN_FIELD, \
    PATTERN_MEDIA = "link", "button", "tab", "accordion", "modal", "menu", "field", "media"

# Conversion-type interactions: an untracked one is a high-priority gap.
CONVERSION_CLASSES = frozenset({CTA, FORM_START, FORM_SUBMIT, DOWNLOAD, SIGNUP, PURCHASE, APPOINTMENT,
                                PHONE, EMAIL, LOGIN})
UNSAFE_CLASSES = frozenset({PURCHASE, APPOINTMENT, FORM_SUBMIT})

DOWNLOAD_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "xlsm", "ppt", "pptx", "csv", "txt", "rtf", "odt", "ods", "odp",
    "zip", "rar", "7z", "gz", "tar", "epub", "dmg", "exe", "msi", "apk", "pkg", "ics", "vcf",
    "jpg", "jpeg", "png", "gif", "webp", "svg", "mp3", "wav",
}
VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "m4v", "avi"}
_VIDEO_HOST_RE = re.compile(r"youtube\.com|youtu\.be|vimeo\.com|wistia\.|dailymotion\.|brightcove|jwplayer|vidyard|loom\.com", re.I)

# Generic intent vocabulary (kinds of actions, several languages) — matched as
# whole words/segments against destination path + accessible name.
_INTENT = [
    (LOGIN, re.compile(r"\b(log ?in|sign ?in|signin|login|my account|anmelden|connexion|se connecter|iniciar sesi[oó]n|accedi)\b", re.I)),
    (SIGNUP, re.compile(r"\b(sign ?up|signup|register|registration|create (an )?account|join|subscribe|newsletter|registrieren|s'inscrire|inscription|registrarse)\b", re.I)),
    (PURCHASE, re.compile(r"\b(buy|purchase|checkout|check out|basket|cart|add to (cart|bag|basket)|order now|pay|payment|warenkorb|kaufen|panier|acheter|comprar|carrito)\b", re.I)),
    (APPOINTMENT, re.compile(r"\b(book|booking|appointment|schedule|reserve|reservation|termin|rendez-vous|reservar|cita)\b", re.I)),
    (SEARCH, re.compile(r"\b(search|suche|recherche|buscar|cerca)\b", re.I)),
]
_DESTRUCTIVE_RE = re.compile(r"\b(log ?out|sign ?out|logout|signout|delete|remove|unsubscribe|deactivate|cancel (my )?(order|subscription|account))\b", re.I)
_SEARCH_FIELD_NAMES = {"q", "s", "query", "search", "keyword", "keywords", "k", "term", "searchterm"}


@dataclass
class Classification:
    kind: str
    pattern: str
    signals: List[str] = field(default_factory=list)
    confidence: str = "medium"           # high | medium | low
    importance: int = 1                   # 3 high, 2 medium, 1 low
    safe: bool = True
    unsafe_reason: Optional[str] = None
    external: bool = False


@dataclass
class Interaction:
    index: int
    element_id: str
    page_url: str
    label: str
    tag: str
    classification: str
    classification_label: str
    pattern: str
    signals: List[str]
    confidence: str
    importance: int
    safe: bool
    unsafe_reason: Optional[str]
    external: bool
    destination: Optional[str]
    selector: str
    visible: bool
    dynamic: bool
    landmark: Optional[str]
    position: Dict[str, int]
    aria: Dict[str, str]
    attributes: Dict[str, str]
    form_id: Optional[str] = None
    signature: str = ""
    # filled by the tester
    tested: bool = False
    status: str = "not_tested"            # success | failed | skipped | not_tested
    outcome: Optional[str] = None
    observed: str = ""
    final_url: Optional[str] = None
    http_status: Optional[int] = None
    screenshots: Dict[str, Optional[str]] = field(default_factory=dict)
    tracking: Dict[str, object] = field(default_factory=dict)
    duplicate_of: Optional[int] = None

    def as_dict(self) -> dict:
        return asdict(self)


def _ext(url: Optional[str]) -> str:
    if not url:
        return ""
    path = urlparse(url).path.lower()
    last = path.rsplit("/", 1)[-1]
    return last.rsplit(".", 1)[-1] if "." in last else ""


def _intent(text: str) -> List[Tuple[str, str]]:
    found = []
    for kind, rx in _INTENT:
        m = rx.search(text)
        if m:
            found.append((kind, m.group(0)))
    return found


def _same_site(url: str, host: str) -> bool:
    h = (urlparse(url).hostname or "").lower()
    strip = lambda x: x[4:] if x.startswith("www.") else x  # noqa: E731
    return strip(h) == strip(host.lower())


def classify(el: DiscoveredElement, forms: Dict[str, DiscoveredForm], host: str) -> Classification:
    signals: List[str] = []
    tag, role = el.tag, (el.role or "").lower()
    attrs = el.attributes or {}
    aria = el.aria or {}
    dest = el.destination or ""
    scheme = urlparse(dest).scheme.lower() if dest else ""
    ext = _ext(dest)
    landmark = (el.landmark or "").lower()
    style = el.style or {}
    text_blob = " ".join(filter(None, [el.accessible_name, el.text, attrs.get("title"), attrs.get("aria-label")]))
    path_blob = urlparse(dest).path.replace("-", " ").replace("_", " ").replace("/", " ") if dest else ""
    cls_tokens = (attrs.get("class") or "").lower()

    # --- UI pattern --------------------------------------------------------
    pattern = PATTERN_LINK if tag == "a" else PATTERN_BUTTON
    if role == "tab" or "aria-selected" in aria and role in ("tab", ""):
        if role == "tab":
            pattern = PATTERN_TAB
            signals.append("role=tab")
    if tag == "summary" or ("aria-expanded" in aria and "aria-controls" in aria and aria.get("aria-haspopup") in (None, "false")):
        if pattern != PATTERN_TAB:
            pattern = PATTERN_ACCORDION
            signals.append("<summary>" if tag == "summary" else "aria-expanded + aria-controls")
    toggle = (attrs.get("data-toggle") or attrs.get("data-bs-toggle") or "").lower()
    if aria.get("aria-haspopup") == "dialog" or toggle == "modal" or "modal" in (attrs.get("data-target") or attrs.get("data-bs-target") or "").lower():
        pattern = PATTERN_MODAL
        signals.append("opens a dialog (aria-haspopup=dialog / data-toggle=modal)")
    elif aria.get("aria-haspopup") in ("true", "menu", "listbox") or role == "menuitem" or toggle == "dropdown":
        pattern = PATTERN_MENU
        signals.append("opens a menu")
    if tag in ("video", "audio", "iframe"):
        pattern = PATTERN_MEDIA
    if tag in ("select", "input", "textarea") and (el.type or "") not in ("submit", "button", "image", "reset"):
        pattern = PATTERN_FIELD

    def result(kind, conf="medium", importance=1, **kw) -> Classification:
        c = Classification(kind=kind, pattern=pattern, signals=signals, confidence=conf, importance=importance, **kw)
        blob = f"{text_blob} {path_blob}"
        if kind in UNSAFE_CLASSES:
            c.safe = False
            c.unsafe_reason = {PURCHASE: "purchase/payment action", APPOINTMENT: "booking action",
                               FORM_SUBMIT: "form submission (never submitted on production sites)"}[kind]
            # A plain link that only *navigates* to a booking page (no query
            # string that could carry an action) is safe to open. Purchase-type
            # controls are never clicked (e.g. GET add-to-cart links exist).
            if kind == APPOINTMENT and tag == "a" and dest and scheme in ("http", "https") \
                    and not urlparse(dest).query and pattern == PATTERN_LINK:
                c.safe, c.unsafe_reason = True, None
        if _DESTRUCTIVE_RE.search(blob):
            c.safe = False
            c.unsafe_reason = "irreversible account action (sign out / delete / unsubscribe)"
            c.signals.append("destructive wording")
        return c

    # --- scheme / file based ---------------------------------------------------
    if scheme == "tel":
        signals.append("tel: link")
        return result(PHONE, "high", 3)
    if scheme == "mailto":
        signals.append("mailto: link")
        return result(EMAIL, "high", 3)
    if tag in ("video", "audio") or (tag == "iframe" and _VIDEO_HOST_RE.search(dest)) or ext in VIDEO_EXTENSIONS:
        signals.append(f"<{tag}>" if tag in ("video", "audio", "iframe") else f".{ext} media file")
        return result(VIDEO, "high", 2)
    if "download" in attrs or (ext and ext in DOWNLOAD_EXTENSIONS and tag == "a"):
        signals.append("download attribute" if "download" in attrs else f".{ext} file")
        return result(DOWNLOAD, "high", 3)

    # --- form context -------------------------------------------------------------
    form = forms.get(el.form_id) if el.form_id else None
    is_search_form = bool(form and (form.role == "search" or any(
        (f.get("type") == "search" or (f.get("name") or "").lower() in _SEARCH_FIELD_NAMES) for f in form.fields)))
    is_submit = el.tag in ("button", "input") and (
        (el.type or "").lower() in ("submit", "image") or (el.tag == "button" and not el.type and form is not None))
    if form is not None and is_submit:
        if is_search_form or landmark == "search":
            signals.append("submit of a search form")
            c = result(SEARCH, "high", 2)
            c.safe, c.unsafe_reason = False, "submits a form (search) — forms are never submitted on production sites"
            return c
        signals.append("submits its form")
        return result(FORM_SUBMIT, "high", 3)
    if (el.type or "").lower() == "search" or role in ("searchbox",) or landmark == "search":
        signals.append("search field / role=search")
        return result(SEARCH, "high", 2)
    if pattern == PATTERN_FIELD:
        if form is not None:
            signals.append("field inside a form")
            return result(FORM_START, "medium", 2)
        return result(OTHER, "low", 1)

    # --- intent (generic vocabulary) --------------------------------------------
    external = bool(dest) and scheme in ("http", "https") and not _same_site(dest, host)
    intents = _intent(f"{text_blob} {path_blob}")
    intent_kind = intents[0][0] if intents else None
    if intents:
        signals.append(f"action wording: “{intents[0][1]}”")

    # --- CTA prominence ------------------------------------------------------------
    cta_score = 0
    if style.get("has_background") and style.get("padded"):
        cta_score += 2
        signals.append("button-like styling")
    if re.search(r"\b(btn|button|cta|primary|action)\b", cls_tokens.replace("-", " ").replace("_", " ")):
        cta_score += 1
        signals.append("button/cta class")
    if tag == "a" and role == "button":
        cta_score += 1
        signals.append("link with role=button")
    if tag in ("button",) or (tag == "input" and (el.type or "") in ("button", "submit")):
        cta_score += 1
    if landmark in ("main", "") and landmark not in ("nav", "navigation", "header", "banner", "footer", "contentinfo"):
        cta_score += 1 if cta_score else 0
    if (style.get("font_size") or 0) >= 17 and style.get("bold"):
        cta_score += 1
    in_nav = landmark in ("nav", "navigation", "header", "banner", "footer", "contentinfo") or role == "menuitem"

    if intent_kind in (LOGIN, SIGNUP, PURCHASE, APPOINTMENT):
        return result(intent_kind, "high" if cta_score >= 2 else "medium", 3, external=external)
    if intent_kind == SEARCH and pattern != PATTERN_LINK:
        return result(SEARCH, "medium", 2)

    if pattern in (PATTERN_TAB, PATTERN_ACCORDION, PATTERN_MODAL, PATTERN_MENU):
        if pattern == PATTERN_MODAL and cta_score >= 2:
            signals.append("prominent dialog trigger")
            return result(CTA, "medium", 3)
        return result(OTHER if pattern != PATTERN_MENU else NAVIGATION, "high", 2 if pattern != PATTERN_MENU else 1)

    if cta_score >= 3 and not in_nav:
        signals.append(f"prominence score {cta_score}")
        return result(CTA, "high" if cta_score >= 4 else "medium", 3, external=external)

    if tag == "a" and dest:
        if in_nav:
            signals.append(f"inside <{landmark or 'nav'}>")
        signals.append("external link" if external else "same-site link")
        return result(NAVIGATION, "high" if in_nav else "medium", 2 if in_nav else 1, external=external)

    if tag in ("button", "input") or role in ("button", "link", "switch") or "onclick" in attrs:
        if cta_score >= 2 and not in_nav:
            signals.append(f"prominence score {cta_score}")
            return result(CTA, "medium", 3)
        return result(OTHER, "low", 1)
    return result(OTHER, "low", 1)


def build_interactions(elements: List[DiscoveredElement], forms: List[DiscoveredForm], host: str) -> List[Interaction]:
    by_form = {f.id: f for f in forms}
    out: List[Interaction] = []
    for el in elements:
        if el.tag == "form":
            continue
        c = classify(el, by_form, host)
        out.append(Interaction(
            index=len(out) + 1, element_id=el.id, page_url=el.page_url, label=el.label[:120], tag=el.tag,
            classification=c.kind, classification_label=CLASS_LABELS[c.kind], pattern=c.pattern,
            signals=c.signals[:8], confidence=c.confidence, importance=c.importance, safe=c.safe,
            unsafe_reason=c.unsafe_reason, external=c.external, destination=el.destination,
            selector=el.selector, visible=el.visible, dynamic=el.dynamic, landmark=el.landmark,
            position=el.position, aria=el.aria, attributes=el.attributes, form_id=el.form_id,
            signature=f"{c.kind}|{el.signature}",
        ))
    # One "Form" interaction per discovered form (focus test, never submitted).
    for f in forms:
        if not f.visible or not f.fields:
            continue
        is_search = f.role == "search" or any((x.get("type") == "search" or (x.get("name") or "").lower()
                                               in _SEARCH_FIELD_NAMES) for x in f.fields)
        if is_search:
            continue
        label = f.heading or f.name or "Form"
        out.append(Interaction(
            index=len(out) + 1, element_id=f.id, page_url=f.page_url, label=f"{label} (form)"[:120], tag="form",
            classification=FORM, classification_label=CLASS_LABELS[FORM], pattern=PATTERN_FIELD,
            signals=[f"{len([x for x in f.fields if x.get('visible')])} visible field(s)", f"method={f.method}"],
            confidence="high", importance=3, safe=True, unsafe_reason=None, external=False,
            destination=f.action, selector=f.selector, visible=f.visible, dynamic=f.dynamic,
            landmark=f.landmark, position=f.position, aria={}, attributes={}, form_id=f.id,
            signature=f"form|{f.signature}",
        ))
    # Mark repeats (e.g. the same nav link on every page) so each is tested once.
    first_by_sig: Dict[str, int] = {}
    for it in out:
        key = it.signature
        if key in first_by_sig:
            it.duplicate_of = first_by_sig[key]
        else:
            first_by_sig[key] = it.index
    return out


def _worth_testing(it: Interaction) -> bool:
    if it.importance < 2 and it.classification == OTHER:
        return False
    if it.pattern == PATTERN_TAB and (it.aria or {}).get("aria-selected") == "true":
        return False                       # already-selected tab: clicking shows nothing new
    if it.pattern == PATTERN_LINK and it.destination and not it.external \
            and normalize_url(urljoin(it.page_url, it.destination)) == normalize_url(it.page_url):
        return False                       # link to the page we're on
    return True


def select_for_testing(interactions: List[Interaction], max_total: int, max_per_page: int) -> List[Interaction]:
    """
    Which interactions get a live test (each reloads its page and captures
    before / highlighted / after evidence):
      1. every high-importance (conversion-type) interaction
      2. one of each remaining kind (classification × UI pattern)
      3. the rest, top of page first
    within the per-page and per-audit limits. Repeats of the same element on
    other pages are tested once.
    """
    pool = [i for i in interactions if i.duplicate_of is None and i.visible and _worth_testing(i)]
    pool.sort(key=lambda i: (i.external, i.position.get("y", 0)))
    high = [i for i in pool if i.importance >= 3]
    firsts, rest, seen_kinds = [], [], set()
    for it in pool:
        if it.importance >= 3:
            continue
        key = (it.classification, it.pattern)
        (rest if key in seen_kinds else firsts).append(it)
        seen_kinds.add(key)
    ordered = high + firsts + rest

    picked: List[Interaction] = []
    per_page: Dict[str, int] = {}
    for it in ordered:
        if len(picked) >= max_total:
            break
        if per_page.get(it.page_url, 0) >= max_per_page:
            continue
        per_page[it.page_url] = per_page.get(it.page_url, 0) + 1
        picked.append(it)
    return picked


# =============================================================================
# Safe interaction testing
# =============================================================================

_STATE_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  const dialogs = [...document.querySelectorAll('[role=dialog], dialog, [aria-modal=true]')].filter(d => {
    const r = d.getBoundingClientRect(); const cs = getComputedStyle(d);
    return r.width > 1 && r.height > 1 && cs.display !== 'none' && cs.visibility !== 'hidden';
  }).length;
  let visible = 0;
  for (const n of document.querySelectorAll('body *')) { if (n.offsetParent !== null) visible++; if (visible > 5000) break; }
  const textLen = (document.body && document.body.innerText || '').length;
  let expanded = null, selected = null, openAttr = null, playing = null;
  if (el) {
    expanded = el.getAttribute('aria-expanded'); selected = el.getAttribute('aria-selected');
    const det = el.closest('details'); openAttr = det ? det.open : null;
    const v = el.tagName === 'VIDEO' || el.tagName === 'AUDIO' ? el : null;
    playing = v ? !v.paused : null;
  }
  return { url: location.href, dialogs, visible, textLen, expanded, selected, openAttr, playing, exists: !!el,
           active: document.activeElement ? (document.activeElement.getAttribute('data-journey-id') || document.activeElement.tagName) : null };
}
"""

SETTLE_AFTER_ACTION_MS = 1_800


@dataclass
class TestContext:
    context: object
    page: object
    capture: object            # journey_tracking.TrackingCapture
    evidence: object           # journey_screenshots.EvidenceWriter
    host: str
    analytics_present: bool = True


async def _reset_to(tc: TestContext, page_url: str, prefix: str) -> None:
    """Load the interaction's page fresh and re-tag its elements (deterministic ids)."""
    # Always reload: every interaction starts from the page's initial state.
    await tc.page.goto(page_url, wait_until="load", timeout=20_000)
    await tc.page.wait_for_timeout(900)
    await tc.page.evaluate(DISCOVER_JS, {"maxElements": 400, "idPrefix": prefix})


async def _http_check(tc: TestContext, url: str) -> Tuple[Optional[int], Optional[str], Optional[int]]:
    from journey.journey_scanner import http_fetch

    status, headers, _ = await http_fetch(tc.context, url, method="HEAD", timeout=12.0)
    if status is None:
        return None, None, None
    lower = {k.lower(): v for k, v in headers.items()}
    size = lower.get("content-length")
    return status, lower.get("content-type"), int(size) if size and size.isdigit() else None


async def test_interaction(tc: TestContext, it: Interaction, page_prefix: str) -> None:
    """Runs one safe interaction and records outcome, screenshots and tracking."""
    from journey.journey_tracking import NOT_APPLICABLE, NOT_TESTED, evaluate_interaction

    sel = f'[data-journey-id="{it.element_id}"]'
    page = tc.page
    try:
        await _reset_to(tc, it.page_url, page_prefix)
        loc = page.locator(sel).first
        if not await loc.count():
            it.status, it.observed = "failed", "Element no longer present after reloading the page."
            return
        try:
            await loc.scroll_into_view_if_needed(timeout=4_000)
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(250)
        it.screenshots["before"] = await tc.evidence.viewport(page, it.page_url, it.index, "before")
        it.screenshots["highlighted"] = await tc.evidence.highlighted(
            page, sel, f"detected: {it.classification_label}", it.page_url, it.index)

        if not it.safe:
            it.status, it.outcome = "skipped", "not_executed_for_safety"
            it.observed = f"Not executed: {it.unsafe_reason}. Element discovered and captured as evidence."
            it.tracking = {"status": NOT_TESTED, "note": "Not tested — action is not executed on production sites."}
            return

        before_state = await page.evaluate(_STATE_JS, sel)
        pre_window = tc.capture.mark()
        await page.wait_for_timeout(150)
        started = tc.capture.mark()
        dest = urljoin(it.page_url, it.destination) if it.destination else None
        kind = it.classification

        if it.external and dest:
            status, ctype, _ = await _http_check(tc, dest)
            it.http_status = status
            it.tested = True
            it.status = "success" if status and status < 400 else "failed"
            it.outcome = "external_link_checked"
            it.observed = (f"External destination responded HTTP {status}." if status
                           else "External destination could not be reached.")
            it.tracking = {"status": NOT_TESTED, "note": "External link checked by HTTP request; not clicked."}
            return

        if kind == FORM:
            fields = page.locator(f'{sel} input:not([type=hidden]):not([type=submit]):not([type=checkbox]):not([type=radio]), '
                                  f'{sel} textarea')
            n = await fields.count()
            focused = False
            for i in range(min(n, 6)):
                f = fields.nth(i)
                if await f.is_visible():
                    await f.click(timeout=3_000)
                    await f.press_sequentially("a", delay=30)
                    await f.fill("")
                    focused = True
                    break
            await page.wait_for_timeout(SETTLE_AFTER_ACTION_MS)
            it.tested = True
            it.status = "success" if focused else "failed"
            it.outcome = "form_focused_not_submitted"
            it.observed = ("Focused and typed into the first visible field, then cleared it. The form was "
                           "NOT submitted (production safety)." if focused else "No visible text field could be focused.")
            it.screenshots["after"] = await tc.evidence.element(page, sel, it.page_url, it.index, "form")
        elif kind == SEARCH and (it.pattern == PATTERN_FIELD or it.tag in ("input", "textarea")):
            await loc.click(timeout=3_000)
            await loc.press_sequentially("test", delay=30)
            await page.wait_for_timeout(SETTLE_AFTER_ACTION_MS)
            it.tested, it.status, it.outcome = True, "success", "search_field_focused"
            it.observed = "Search field focused and a query typed (not submitted)."
            it.screenshots["after"] = await tc.evidence.viewport(page, it.page_url, it.index, "after")
            await loc.fill("")
        elif kind == DOWNLOAD and dest:
            status, ctype, size = await _http_check(tc, dest)
            it.http_status = status
            try:
                async with page.expect_download(timeout=6_000):
                    await loc.click(timeout=4_000)
            except Exception:  # noqa: BLE001 — opened inline (PDF viewer) or not a browser download
                pass
            await page.wait_for_timeout(SETTLE_AFTER_ACTION_MS)
            it.tested = True
            it.status = "success" if status and status < 400 else "failed"
            it.outcome = "download_checked"
            it.observed = (f"Download resource responded HTTP {status}"
                           + (f" ({ctype}" + (f", {size} bytes" if size else "") + ")" if ctype else "")
                           + "." if status else "Download resource could not be reached.")
            it.screenshots["after"] = await tc.evidence.viewport(page, it.page_url, it.index, "after")
        elif kind == VIDEO and it.tag in ("video", "audio"):
            await loc.evaluate("v => { v.muted = true; return v.play && v.play().catch(() => {}); }")
            await page.wait_for_timeout(SETTLE_AFTER_ACTION_MS)
            after = await page.evaluate(_STATE_JS, sel)
            it.tested = True
            it.status = "success" if after.get("playing") else "failed"
            it.outcome = "video_played" if after.get("playing") else "video_did_not_play"
            it.observed = "Video started playing (muted)." if after.get("playing") else "Video did not start playing."
            it.screenshots["after"] = await tc.evidence.viewport(page, it.page_url, it.index, "after")
        else:
            # Links, CTAs, buttons, tabs, accordions, modal triggers, menus, tel:/mailto:, iframe players.
            response_status = {"value": None}

            def _on_response(resp):
                try:
                    if resp.request.is_navigation_request() and resp.request.frame == page.main_frame:
                        response_status["value"] = resp.status
                except Exception:  # noqa: BLE001
                    pass

            page.on("response", _on_response)
            try:
                if it.tag == "iframe":
                    await loc.click(timeout=4_000, position={"x": 20, "y": 20})
                else:
                    await loc.click(timeout=5_000)
            except Exception:  # noqa: BLE001 — covered element: fall back to a DOM click
                try:
                    await loc.evaluate("el => el.click()")
                except Exception as exc:  # noqa: BLE001
                    it.tested, it.status = True, "failed"
                    it.observed = f"Could not click the element: {str(exc)[:160]}"
                    return
            try:
                await page.wait_for_load_state("load", timeout=8_000)
            except Exception:  # noqa: BLE001
                pass
            await page.wait_for_timeout(SETTLE_AFTER_ACTION_MS)
            try:
                page.remove_listener("response", _on_response)
            except Exception:  # noqa: BLE001
                pass

            after = await page.evaluate(_STATE_JS, sel) if not page.is_closed() else {}
            it.tested = True
            it.final_url = page.url
            it.http_status = response_status["value"]
            navigated = normalize_url(page.url) != normalize_url(before_state.get("url") or it.page_url)
            if navigated:
                ok = it.http_status is None or it.http_status < 400
                it.status = "success" if ok else "failed"
                it.outcome = "navigated" if ok else "broken_destination"
                it.observed = (f"Navigated to {page.url}" + (f" (HTTP {it.http_status})" if it.http_status else "") + ".")
                expected = normalize_url(dest) if dest and urlparse(dest).scheme in ("http", "https") else None
                if ok and expected and normalize_url(page.url) != expected and it.pattern == PATTERN_LINK:
                    it.outcome = "unexpected_navigation"
                    it.observed += f" Expected {expected}."
            elif (after.get("dialogs") or 0) > (before_state.get("dialogs") or 0):
                it.status, it.outcome, it.observed = "success", "modal_opened", "A dialog/modal opened."
            elif after.get("expanded") != before_state.get("expanded") or after.get("openAttr") != before_state.get("openAttr"):
                it.status, it.outcome = "success", "expanded" if (after.get("expanded") == "true" or after.get("openAttr")) else "collapsed"
                it.observed = "Toggled expanded state (aria-expanded / details)."
            elif after.get("selected") != before_state.get("selected"):
                it.status, it.outcome, it.observed = "success", "tab_selected", "Tab selection changed."
            elif urlparse(dest or "").scheme in ("tel", "mailto"):
                ok = bool(re.match(r"^(tel:\+?[\d\s().-]{5,}|mailto:[^@\s]+@[^@\s]+\.[^@\s]+)", dest or "", re.I))
                it.status = "success" if ok else "failed"
                it.outcome = "contact_link_activated"
                it.observed = f"{'Valid' if ok else 'Malformed'} {urlparse(dest).scheme}: link activated (no app opened in the test browser)."
            elif abs((after.get("visible") or 0) - (before_state.get("visible") or 0)) > 3 \
                    or abs((after.get("textLen") or 0) - (before_state.get("textLen") or 0)) > 5:
                it.status, it.outcome, it.observed = "success", "content_changed", "Page content changed after the click."
            elif it.pattern == PATTERN_LINK and dest and normalize_url(dest) == normalize_url(it.page_url):
                it.status, it.outcome, it.observed = "success", "same_page_link", "Link points to the current page."
            else:
                it.status, it.outcome = "failed", "no_visible_effect"
                it.observed = "Clicked, but no navigation, dialog, expansion or content change was observed."
            if it.outcome == "modal_opened":
                it.screenshots["after"] = await tc.evidence.viewport(page, it.page_url, it.index, "after")
                try:
                    await page.keyboard.press("Escape")
                except Exception:  # noqa: BLE001
                    pass
            else:
                it.screenshots["after"] = await tc.evidence.viewport(page, it.page_url, it.index, "after")

        end = tc.capture.mark()
        if it.tested:
            tracking = evaluate_interaction(tc.capture, started, end, pre_window, tc.analytics_present)
            it.tracking = tracking.as_dict()
        else:
            it.tracking = {"status": NOT_APPLICABLE}
    except Exception as exc:  # noqa: BLE001 — one interaction never stops the run
        logger.info(f"journey: interaction {it.index} ({it.label}) failed: {exc}")
        it.status = "failed" if it.tested else "not_tested"
        it.observed = it.observed or f"Interaction could not be tested: {str(exc)[:200]}"
