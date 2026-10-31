"""
Works out what each discovered element is for, then safely tests the important ones.

Classification uses several signals, never just the button text: structure
(tag, role, aria-*), destination (tel:, mailto:, files, same-site or not),
context (nav, header, form...), styling (looks like a button?) and a small
multilingual list of action words (sign in, register, book...).

Never clicked: form submits, purchases, payments, bookings, sign-out,
delete/unsubscribe. They are still found and screenshotted.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from config.logging import logger
from journey.journey_scanner import DISCOVER_JS, DiscoveredElement, DiscoveredForm, normalize_url

# Classifications
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

# UI pattern: how it behaves (separate from what it's for).
PATTERN_LINK, PATTERN_BUTTON, PATTERN_TAB, PATTERN_ACCORDION, PATTERN_MODAL, PATTERN_MENU, PATTERN_FIELD, \
    PATTERN_MEDIA, PATTERN_CAROUSEL = "link", "button", "tab", "accordion", "modal", "menu", "field", "media", "carousel"

# Conversion interactions: an untracked one is a serious gap.
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

# Action words in several languages, matched against the link path and the element's name.
_INTENT = [
    (LOGIN, re.compile(r"\b(log ?in|sign ?in|signin|login|my account|anmelden|connexion|se connecter|iniciar sesi[oó]n|accedi)\b", re.I)),
    (SIGNUP, re.compile(r"\b(sign ?up|signup|register|registration|create (an )?account|join|subscribe|newsletter|registrieren|s'inscrire|inscription|registrarse)\b", re.I)),
    (PURCHASE, re.compile(r"\b(buy|purchase|checkout|check out|basket|cart|add to (cart|bag|basket)|order now|pay|payment|warenkorb|kaufen|panier|acheter|comprar|carrito)\b", re.I)),
    (APPOINTMENT, re.compile(r"\b(book|booking|appointment|schedule|reserve|reservation|termin|rendez-vous|reservar|cita)\b", re.I)),
    (SEARCH, re.compile(r"\b(search|suche|recherche|buscar|cerca)\b", re.I)),
]
_DESTRUCTIVE_RE = re.compile(r"\b(log ?out|sign ?out|logout|signout|delete|remove|unsubscribe|deactivate|cancel (my )?(order|subscription|account))\b", re.I)
# Slider controls (arrows, dots) are page UI, never conversions.
_CAROUSEL_CLASS_RE = re.compile(r"(^|[\s_-])(slick|swiper|carousel|slider|glide|splide|owl|flickity|embla|keen-slider)"
                                r"([\s_-]|$)", re.I)
_CAROUSEL_WORDS_RE = re.compile(r"\b(slides?|slide \d|next|previous|prev|successiv[ao]|precedente|weiter|zur[üu]ck|"
                                r"vorherige?|n[äa]chste|suivante?|pr[ée]c[ée]dente?|siguiente|anterior|diapositiva)\b", re.I)
_ACTIVE_CLASS_RE = re.compile(r"(^|[\s_-])(active|is-active|selected|current)([\s_-]|$)", re.I)
_TAB_CLASS_RE = re.compile(r"(^|[\s_-])(tab|tabs|tab-item|tablink|tab-link|nav-tab)([\s_-]|$)", re.I)
_DISABLED_CLASS_RE = re.compile(r"(^|[\s_-])(disabled|is-disabled)([\s_-]|$)", re.I)



def contact_link_check(dest: Optional[str]) -> tuple:
    """(valid, note) for a tel: / mailto: link. Phones accept tel:// and spaced or %20 numbers too."""
    from urllib.parse import unquote
    raw = unquote((dest or "").strip())
    scheme, _, rest = raw.partition(":")
    scheme = scheme.lower()
    if scheme == "tel":
        number = rest.split("?")[0].split(";")[0]
        digits = re.sub(r"\D", "", number)
        if len(digits) >= 3 and re.fullmatch(r"[/\s+\d().\-]*", number or "x"):
            note = (" Number written as tel:// (non-standard but dialled by phones; tel:+39… is preferred)."
                    if number.startswith("//") else "")
            return True, note
        return False, ""
    if scheme == "mailto":
        address = rest.split("?")[0].lstrip("/")
        return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address)), ""
    return False, ""

def is_disabled(attrs: Dict[str, str], aria: Dict[str, str]) -> bool:
    return ("disabled" in (attrs or {}) or (aria or {}).get("aria-disabled") == "true"
            or bool(_DISABLED_CLASS_RE.search((attrs or {}).get("class") or "")))


def is_already_active(attrs: Dict[str, str], aria: Dict[str, str]) -> bool:
    """Already-selected tab/option: clicking shows nothing new."""
    return ((aria or {}).get("aria-selected") == "true" or (aria or {}).get("aria-current") in ("page", "true", "step")
            or bool(_ACTIVE_CLASS_RE.search((attrs or {}).get("class") or "")))


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
    consent_control: bool = False         # inside a cookie banner: tested by the Consent module
    # set by the tester
    tested: bool = False
    status: str = "not_tested"            # success | failed | skipped | not_tested | consent_control
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

    # UI pattern
    pattern = PATTERN_LINK if tag == "a" else PATTERN_BUTTON
    if role == "tab" or "aria-selected" in aria and role in ("tab", ""):
        if role == "tab":
            pattern = PATTERN_TAB
            signals.append("role=tab")
    if tag == "summary" or ("aria-expanded" in aria and "aria-controls" in aria and aria.get("aria-haspopup") in (None, "false")):
        if pattern != PATTERN_TAB:
            pattern = PATTERN_ACCORDION
            signals.append("<summary>" if tag == "summary" else "aria-expanded + aria-controls")
    if pattern == PATTERN_BUTTON and tag != "a" and _TAB_CLASS_RE.search(attrs.get("class") or ""):
        pattern = PATTERN_TAB
        signals.append("tab control (class)")
    if tag != "a" or not dest or dest.endswith("#"):
        if _CAROUSEL_CLASS_RE.search(attrs.get("class") or "") or (
                tag in ("button", "li", "span", "div") and not el.form_id
                and _CAROUSEL_WORDS_RE.search(text_blob) and len(text_blob) < 60):
            pattern = PATTERN_CAROUSEL
            signals.append("slider / carousel control")
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
            # A plain link to a booking page is safe to open. Purchase controls are never clicked.
            if kind == APPOINTMENT and tag == "a" and dest and scheme in ("http", "https") \
                    and not urlparse(dest).query and pattern == PATTERN_LINK:
                c.safe, c.unsafe_reason = True, None
        if _DESTRUCTIVE_RE.search(blob):
            c.safe = False
            c.unsafe_reason = "irreversible account action (sign out / delete / unsubscribe)"
            c.signals.append("destructive wording")
        return c

    # Page UI that is never a conversion
    if pattern == PATTERN_CAROUSEL:
        return result(OTHER, "high", 1)

    # Scheme / file based
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

    # Form context
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

    # Action words
    external = bool(dest) and scheme in ("http", "https") and not _same_site(dest, host)
    intents = _intent(f"{text_blob} {path_blob}")
    intent_kind = intents[0][0] if intents else None
    if intents:
        signals.append(f"action wording: “{intents[0][1]}”")

    # Call-to-action prominence
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
        # A plain <button> is only a CTA if it looks like one (button styling or btn/cta class).
        looks_like_cta = any(sig in signals for sig in ("button-like styling", "button/cta class"))
        if cta_score >= 2 and looks_like_cta and not in_nav:
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
            consent_control=bool(el.in_consent),
            status="consent_control" if el.in_consent else "not_tested",
            observed=CONSENT_CONTROL_NOTE if el.in_consent else "",
            tracking={"status": "not_applicable", "note": "Cookie-banner control — see the Consent module."} if el.in_consent else {},
        ))
    # One "Form" interaction per form (focus test only, never submitted).
    for f in forms:
        if not f.visible or not f.fields or f.in_consent:
            continue                      # cookie-banner forms belong to the Consent module
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


CONSENT_CONTROL_NOTE = ("Cookie-banner control. Not clicked during the journey (it would change consent "
                        "mid-scan); the Consent module tests the banner's buttons.")

# Test order among important interactions: forms first, then other conversions, then CTAs.
_TEST_PRIORITY = {FORM: 0, SIGNUP: 1, FORM_START: 1, PURCHASE: 2, APPOINTMENT: 2, DOWNLOAD: 3}


def _worth_testing(it: Interaction) -> bool:
    if it.consent_control:
        return False
    if is_disabled(it.attributes, it.aria):
        return False                       # disabled control
    if it.pattern == PATTERN_CAROUSEL:
        return False                       # slider controls
    if it.pattern in (PATTERN_TAB, PATTERN_BUTTON) and it.tag != "a" and is_already_active(it.attributes, it.aria):
        return False                       # already selected
    if it.importance < 2 and it.classification == OTHER:
        return False
    if it.pattern == PATTERN_TAB and (it.aria or {}).get("aria-selected") == "true":
        return False                       # already-selected tab
    if it.pattern == PATTERN_LINK and it.destination and not it.external \
            and normalize_url(urljoin(it.page_url, it.destination)) == normalize_url(it.page_url):
        return False                       # link to the current page
    return True


def select_for_testing(interactions: List[Interaction], max_total: int, max_per_page: int) -> List[Interaction]:
    """Which interactions get a live test: every important one, then one of each
    remaining kind, then the rest from the top of the page, within the per-page
    and per-audit limits. Repeats are tested once.
    """
    pool = [i for i in interactions if i.duplicate_of is None and i.visible and _worth_testing(i)]
    pool.sort(key=lambda i: (i.external, i.position.get("y", 0)))
    high = sorted((i for i in pool if i.importance >= 3),
                  key=lambda i: (_TEST_PRIORITY.get(i.classification, 4), i.external, i.position.get("y", 0)))
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


# Safe interaction testing

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
NEW_TAB_EXTRA_WAIT_MS = 3_000     # extra wait for a new tab opened late by a tag manager
ANALYTICS_EXTRA_WAIT_MS = 3_500   # analytics tools send in batches: give the hit time to leave

_MUTATION_START_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  window.__apMut = { count: 0, self: false, y: window.scrollY };
  if (window.__apMutObs) window.__apMutObs.disconnect();
  window.__apMutObs = new MutationObserver((list) => {
    for (const m of list) {
      if (m.target && m.target.closest && m.target.closest('[data-journey-hl]')) continue;
      window.__apMut.count += 1;
      if (el && (m.target === el) && m.type === 'attributes' && (m.attributeName === 'class' || m.attributeName.startsWith('aria-'))) window.__apMut.self = true;
    }
  });
  window.__apMutObs.observe(document.body, { subtree: true, childList: true, attributes: true,
                                            attributeFilter: ['class', 'style', 'hidden', 'aria-hidden', 'aria-selected', 'aria-expanded', 'aria-current'] });
  return true;
}
"""
_MUTATION_READ_JS = r"""
() => {
  const m = window.__apMut || { count: 0, self: false, y: window.scrollY };
  if (window.__apMutObs) window.__apMutObs.disconnect();
  return { count: m.count, self_changed: m.self, scrolled: Math.abs(window.scrollY - m.y) };
}
"""


@dataclass
class TestContext:
    context: object
    page: object
    capture: object            # journey_tracking.TrackingCapture
    evidence: object           # journey_screenshots.EvidenceWriter
    host: str
    analytics_present: bool = True


async def _reset_to(tc: TestContext, page_url: str, prefix: str) -> None:
    """Reloads the page and re-tags its elements."""
    # Always reload so every test starts from the same state.
    from config.browser import goto_page

    from journey.browser_session import is_refused_error

    for delay_ms in (2_000, 5_000, None):
        try:
            await goto_page(tc.page, page_url, load_wait_ms=3_000)
            break
        except Exception as exc:  # noqa: BLE001
            # Bot protection sometimes refuses a burst of page loads: pause, then try again.
            if delay_ms is None or not is_refused_error(exc):
                raise
            await tc.page.wait_for_timeout(delay_ms)
    await tc.page.wait_for_timeout(600)
    return await tc.page.evaluate(DISCOVER_JS, {"maxElements": 1_500, "idPrefix": prefix, "lite": True}) or {}


def _raw_signature(it: Interaction) -> str:
    """The element's signature (tag + link or tag + text)."""
    return (it.signature or "").split("|", 1)[1] if "|" in (it.signature or "") else ""


def relocate_element(it: Interaction, data: dict) -> Optional[str]:
    """Finds the element again after a reload. Element order can change between
    loads (sliders, personalised blocks, late banners), so match by signature,
    closest to the original position. Returns the new data-journey-id.
    """
    raw = _raw_signature(it)
    pool = (data.get("forms") or []) if it.tag == "form" else (data.get("elements") or [])
    if raw:
        same = [e for e in pool if e.get("signature") == raw]
        if same:
            y0 = (it.position or {}).get("y", 0)
            x0 = (it.position or {}).get("x", 0)
            same.sort(key=lambda e: (not e.get("visible", True),
                                     abs((e.get("position") or {}).get("y", 0) - y0)
                                     + abs((e.get("position") or {}).get("x", 0) - x0)))
            return same[0].get("id")
    if it.selector:
        for e in pool:
            if e.get("selector") == it.selector:
                return e.get("id")
    return None


def _click_event(events) -> Optional[str]:
    """Name of the first click/interaction event the site pushed for this click, if any."""
    for e in events:
        if e.source == "dataLayer" and not e.is_lifecycle and e.event:
            return e.event
    return None


async def _http_check(tc: TestContext, url: str) -> Tuple[Optional[int], Optional[str], Optional[int]]:
    from journey.journey_scanner import http_fetch

    status, headers, _ = await http_fetch(tc.context, url, method="HEAD", timeout=12.0)
    if status is None:
        return None, None, None
    lower = {k.lower(): v for k, v in headers.items()}
    size = lower.get("content-length")
    return status, lower.get("content-type"), int(size) if size and size.isdigit() else None


async def test_interaction(tc: TestContext, it: Interaction, page_prefix: str) -> None:
    """Runs one safe interaction and records the outcome, screenshots and tracking."""
    from journey.journey_tracking import NOT_APPLICABLE, NOT_TESTED, evaluate_interaction

    sel = f'[data-journey-id="{it.element_id}"]'
    page = tc.page
    try:
        data = await _reset_to(tc, it.page_url, page_prefix)
        found = relocate_element(it, data if isinstance(data, dict) else {})
        if found:
            sel = f'[data-journey-id="{found}"]'
        elif it.selector:
            # Not found by id: try the CSS path.
            try:
                if await page.locator(it.selector).count() == 1:
                    sel = it.selector
            except Exception:  # noqa: BLE001 — invalid selector on this page
                pass
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
            # Links, CTAs, buttons, tabs, accordions, modals, menus, tel:/mailto:, video players.
            response_status = {"value": None, "redirected_from": None}
            popups: list = []

            def _on_response(resp):
                try:
                    if resp.request.is_navigation_request() and resp.request.frame == page.main_frame:
                        response_status["value"] = resp.status
                        first = resp.request
                        while first.redirected_from is not None:
                            first = first.redirected_from
                        if first is not resp.request:
                            response_status["redirected_from"] = first.url
                except Exception:  # noqa: BLE001
                    pass

            def _on_popup(p):
                if p is not page and p not in popups:
                    popups.append(p)

            page.on("response", _on_response)
            page.on("popup", _on_popup)
            # Some sites open the new tab without an opener (noopener) or a moment later
            # (tag managers wait for their tags before opening it): watch the whole browser too.
            context = getattr(tc, "context", None)
            if context is not None:
                try:
                    context.on("page", _on_popup)
                except Exception:  # noqa: BLE001
                    context = None
            # Count page changes caused by the click: a reliable "something happened" signal.
            baseline = 0
            try:
                await page.evaluate(_MUTATION_START_JS, sel)
                # Measure background changes (sliders, chat widgets) first so they aren't credited to the click.
                await page.wait_for_timeout(700)
                baseline = int(await page.evaluate(
                    "() => { const m = window.__apMut || {count: 0}; const b = m.count; m.count = 0; m.self = false; return b; }") or 0)
            except Exception:  # noqa: BLE001
                pass
            started = tc.capture.mark()   # tracking attribution starts at the click
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
            opens_new_tab = (it.attributes or {}).get("target", "").lower() == "_blank"
            if opens_new_tab and not popups and normalize_url(page.url) == normalize_url(
                    before_state.get("url") or it.page_url):
                # Tag managers can hold a new-tab link for up to ~2 s while their tags fire.
                for _ in range(int(NEW_TAB_EXTRA_WAIT_MS / 250)):
                    if popups:
                        break
                    await page.wait_for_timeout(250)
            for name, handler in (("response", _on_response), ("popup", _on_popup)):
                try:
                    page.remove_listener(name, handler)
                except Exception:  # noqa: BLE001
                    pass
            if context is not None:
                try:
                    context.remove_listener("page", _on_popup)
                except Exception:  # noqa: BLE001
                    pass

            after = await page.evaluate(_STATE_JS, sel) if not page.is_closed() else {}
            mutations = {}
            try:
                mutations = await page.evaluate(_MUTATION_READ_JS) if not page.is_closed() else {}
            except Exception:  # noqa: BLE001 — page navigated away
                pass
            it.tested = True
            it.final_url = page.url
            it.http_status = response_status["value"]
            navigated = normalize_url(page.url) != normalize_url(before_state.get("url") or it.page_url)
            if popups and not navigated:
                # Opened in a new tab: a working link. Check where it landed, then close it.
                pop = popups[0]
                try:
                    await pop.wait_for_load_state("domcontentloaded", timeout=10_000)
                except Exception:  # noqa: BLE001
                    pass
                pop_url = ""
                try:
                    pop_url = pop.url
                except Exception:  # noqa: BLE001
                    pass
                status = None
                if pop_url.startswith("http"):
                    status, _ctype, _size = await _http_check(tc, pop_url)
                for p_ in popups:
                    try:
                        await p_.close()
                    except Exception:  # noqa: BLE001
                        pass
                it.final_url = pop_url or None
                it.http_status = status
                ok = status is None or status < 400
                it.status = "success" if ok else "failed"
                it.outcome = "opened_new_tab" if ok else "broken_destination"
                it.observed = (f"Opened in a new tab: {pop_url or 'about:blank'}"
                               + (f" (HTTP {status})" if status else "") + ".")
            elif navigated:
                ok = it.http_status is None or it.http_status < 400
                it.status = "success" if ok else "failed"
                it.outcome = "navigated" if ok else "broken_destination"
                it.observed = (f"Navigated to {page.url}" + (f" (HTTP {it.http_status})" if it.http_status else "") + ".")
                expected = normalize_url(dest) if dest and urlparse(dest).scheme in ("http", "https") else None
                landed = normalize_url(page.url)
                if ok and expected and landed != expected and it.pattern == PATTERN_LINK:
                    redirected_from = response_status.get("redirected_from")
                    if redirected_from and normalize_url(redirected_from) == expected:
                        # Server redirect to the link's new address: works as intended.
                        it.outcome = "redirected"
                        it.observed += f" The link points to {expected}, which redirects here."
                    else:
                        it.outcome = "unexpected_navigation"
                        it.observed += f" Expected {expected}."
            elif (after.get("dialogs") or 0) > (before_state.get("dialogs") or 0):
                it.status, it.outcome, it.observed = "success", "modal_opened", "A dialog/modal opened."
            elif after.get("expanded") != before_state.get("expanded") or after.get("openAttr") != before_state.get("openAttr"):
                it.status, it.outcome = "success", "expanded" if (after.get("expanded") == "true" or after.get("openAttr")) else "collapsed"
                it.observed = "Toggled expanded state (aria-expanded / details)."
            elif after.get("selected") != before_state.get("selected") or mutations.get("self_changed"):
                it.status, it.outcome, it.observed = "success", "tab_selected", "The control switched to its selected/active state."
            elif urlparse(dest or "").scheme in ("tel", "mailto"):
                ok, note = contact_link_check(dest)
                it.status = "success" if ok else "failed"
                it.outcome = "contact_link_activated"
                it.observed = (f"{'Valid' if ok else 'Malformed'} {urlparse(dest).scheme}: link activated "
                               f"(no app opened in the test browser).{note}")
            elif abs((after.get("visible") or 0) - (before_state.get("visible") or 0)) > 3 \
                    or abs((after.get("textLen") or 0) - (before_state.get("textLen") or 0)) > 5 \
                    or (mutations.get("count") or 0) >= 3 + baseline * 6:
                it.status, it.outcome = "success", "content_changed"
                it.observed = "Page content changed after the click" + (
                    f" ({mutations.get('count')} page updates)." if mutations.get("count") else ".")
            elif (mutations.get("scrolled") or 0) > 80:
                it.status, it.outcome, it.observed = "success", "scrolled", "The page scrolled to another section."
            elif it.pattern == PATTERN_LINK and dest and normalize_url(dest) == normalize_url(it.page_url):
                it.status, it.outcome, it.observed = "success", "same_page_link", "Link points to the current page."
            elif opens_new_tab and dest and urlparse(dest).scheme in ("http", "https"):
                # A new-tab link whose tab the test browser could not see: check the destination itself.
                status, _ctype, _size = await _http_check(tc, dest)
                it.http_status = status
                it.final_url = dest
                ok = status is not None and status < 400
                it.status = "success" if ok else "failed"
                it.outcome = "opened_new_tab" if ok else "broken_destination"
                it.observed = (f"Link opens in a new tab (target=_blank): {dest}"
                               + (f" (HTTP {status})." if status else " (destination could not be reached)."))
            elif registered := _click_event(tc.capture.between(started)):
                # No visible change in this tab, but the site's own code reacted to the click.
                it.status, it.outcome = "success", "click_registered"
                it.observed = (f"No visible change in this tab, but the site registered the click "
                               f"(event \"{registered}\").")
            else:
                it.status, it.outcome = "failed", "no_visible_effect"
                it.observed = ("Clicked, but nothing happened: no navigation, new tab, dialog, expansion or "
                               "page change was observed.")
            if it.outcome == "modal_opened":
                it.screenshots["after"] = await tc.evidence.viewport(page, it.page_url, it.index, "after")
                try:
                    await page.keyboard.press("Escape")
                except Exception:  # noqa: BLE001
                    pass
            else:
                it.screenshots["after"] = await tc.evidence.viewport(page, it.page_url, it.index, "after")

        if it.tested and it.status == "success":
            # Analytics may send a moment later: wait briefly for a real request.
            waited = 0
            while waited < ANALYTICS_EXTRA_WAIT_MS and not any(
                    e.source == "network" and not e.is_lifecycle for e in tc.capture.between(started)):
                await asyncio.sleep(0.5)
                waited += 500
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
