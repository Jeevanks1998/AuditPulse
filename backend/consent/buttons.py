"""
consent/buttons.py

Consent-control detection, scoped to the consent banner.

The old version scanned every <button>/<a>/<input> on the whole page,
so an unrelated "Continue" button in a checkout form or a "Settings"
link in the nav could be reported as the banner's Accept or Manage
control. This version:

  1. locates the consent banner/container first (known CMP selectors,
     an ARIA dialog that talks about cookies/consent, or the smallest
     element that both mentions cookies/consent and holds a consent
     control);
  2. inventories clickable controls *inside that container only*;
  3. keeps each control's exact visible text, and classifies it into a
     semantic action separately:

        Displayed text:  "Accept only strictly necessary cookies"
        Detected action: reject_non_essential
        Evidence:        Rendered consent banner

Classification rules worth calling out:
  * a bare "Continue" is NOT accept ("Accept and continue" is);
    "Continue without accepting" is reject_non_essential
  * "OK" / "Got it" are acknowledge, NOT accept
  * "Close" / "Dismiss" / "×" are dismiss, NOT reject

The same label rules (`classify_label`) and container selectors
(`CONSENT_CONTAINER_SELECTORS`) are used by consent/runtime.py against
the *rendered* page, which is the authoritative source for
client-rendered CMPs (OneTrust, Didomi, Sourcepoint…) whose banner
never exists in the raw HTML this module reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from crawler.parser import ParsedPage

MODULE = "consent"
CATEGORY = "buttons"

# ---- semantic actions ------------------------------------------------------
ACCEPT_ALL = "accept_all"
ACCEPT = "accept"
REJECT_ALL = "reject_all"
REJECT = "reject"
REJECT_NON_ESSENTIAL = "reject_non_essential"
MANAGE_PREFERENCES = "manage_preferences"
SAVE_PREFERENCES = "save_preferences"
DISMISS = "dismiss"
ACKNOWLEDGE = "acknowledge"
UNCLASSIFIED = "unclassified"

ACCEPT_ACTIONS = frozenset({ACCEPT_ALL, ACCEPT})
REJECT_ACTIONS = frozenset({REJECT_ALL, REJECT, REJECT_NON_ESSENTIAL})
MANAGE_ACTIONS = frozenset({MANAGE_PREFERENCES})
CONSENT_ACTIONS = ACCEPT_ACTIONS | REJECT_ACTIONS | MANAGE_ACTIONS | frozenset({SAVE_PREFERENCES})

# Preference order when choosing which detected control to click.
ACCEPT_CLICK_ORDER = (ACCEPT_ALL, ACCEPT)
REJECT_CLICK_ORDER = (REJECT_ALL, REJECT, REJECT_NON_ESSENTIAL)

ACTION_LABELS = {
    ACCEPT_ALL: "Accept all",
    ACCEPT: "Accept",
    REJECT_ALL: "Reject all",
    REJECT: "Reject",
    REJECT_NON_ESSENTIAL: "Reject non-essential (necessary only)",
    MANAGE_PREFERENCES: "Manage preferences",
    SAVE_PREFERENCES: "Save preferences",
    DISMISS: "Dismiss / close",
    ACKNOWLEDGE: "Acknowledge (OK)",
    UNCLASSIFIED: "Unclassified",
}

EVIDENCE_RENDERED = "Rendered consent banner"
EVIDENCE_STATIC = "Consent banner markup (static HTML)"

# ---- label classification ---------------------------------------------------
# Applied to a normalized label (lower-case, "&" -> "and", punctuation
# stripped, whitespace collapsed). Ordered: the first matching rule wins,
# so the more specific "necessary only" wordings come before plain accept.
_C = "(?: cookies?)?"  # optional trailing "cookie(s)"

_RULES: List[Tuple[str, re.Pattern]] = [
    (REJECT_NON_ESSENTIAL, re.compile(
        r"^(?:"
        rf"(?:accept|allow|use|continue with|i accept|only accept)? ?(?:only )?(?:the )?(?:strictly )?(?:necessary|essential|required|functional only){_C}(?: only)?"
        rf"|only (?:accept |allow |use )?(?:the )?(?:strictly )?(?:necessary|essential|required){_C}"
        r"|continue without (?:accepting|agreeing|consenting)(?: cookies)?"
        rf"|(?:reject|decline|refuse|deny|disable) (?:all )?(?:non ?essential|optional|additional|unnecessary|marketing|analytics){_C}"
        rf"|(?:accept|allow) (?:only )?(?:the )?(?:strictly )?(?:necessary|essential|required){_C}(?: only)?"
        # de / fr / es / it
        r"|nur (?:notwendige|essenzielle|erforderliche)(?: cookies)?(?: (?:akzeptieren|zulassen|verwenden))?"
        r"|continuer sans accepter|refuser les cookies non essentiels|uniquement les cookies n[ée]cessaires"
        r"|solo (?:cookies )?(?:necesarias|necesarios|esenciales)|solo necessari|continua senza accettare"
        r")$")),
    (REJECT_ALL, re.compile(
        rf"^(?:(?:reject|decline|deny|refuse|disable|block) all{_C}(?: and close)?"
        r"|alle ablehnen|tout refuser|rechazar todo|rechazar todas|rifiuta tutti|rifiuta tutto|alles weigeren)$")),
    (REJECT, re.compile(
        rf"^(?:(?:i )?(?:reject|decline|deny|refuse|disagree){_C}"
        r"|i (?:do not|dont|don't) (?:accept|agree)|no thanks|no thank you"
        r"|ablehnen|refuser|rechazar|rifiuta|weigeren)$")),
    (ACCEPT_ALL, re.compile(
        rf"^(?:(?:yes )?(?:i )?(?:accept|allow|agree to|consent to|enable) all{_C}(?: and (?:continue|close|proceed))?"
        r"|alle akzeptieren|alle zulassen|alle cookies akzeptieren|tout accepter|accepter tout|aceptar todo|aceptar todas|accetta tutti|accetta tutto|alles accepteren)$")),
    (ACCEPT, re.compile(
        rf"^(?:(?:yes )?(?:i )?(?:accept|allow|agree|consent){_C}(?: and (?:continue|close|proceed))?"
        rf"|(?:accept|allow) (?:the )?cookies"
        r"|akzeptieren|zustimmen|einverstanden|accepter|j'accepte|aceptar|accetta|accetto|accepteren)$")),
    (SAVE_PREFERENCES, re.compile(
        r"^(?:(?:save|confirm|submit|apply|update)(?: my)? (?:preferences|settings|choices|choice|selection|consent)"
        r"|allow selection|accept selection|accept selected|save and (?:exit|close)|save|confirm"
        r"|auswahl (?:speichern|best[äa]tigen|erlauben)|enregistrer|guardar|salva)$")),
    (MANAGE_PREFERENCES, re.compile(
        r"^(?:(?:manage|customi[sz]e|personali[sz]e|configure|adjust|change|set|edit)"
        r"(?: (?:my|your|cookie|privacy))?(?: (?:preferences|settings|choices|cookies|options|consent|purposes))?"
        r"|(?:cookie|privacy|consent|data) (?:settings|preferences|choices|options)"
        r"|(?:your )?privacy (?:settings|choices)|more options|options|settings|preferences"
        r"|show (?:purposes|details|vendors|preferences)|let me choose|choose cookies"
        r"|einstellungen|cookie einstellungen|anpassen|personnaliser|param[eè]tres|g[ée]rer les cookies"
        r"|configurar|personalizar|preferenze|personalizza|instellingen)$")),
    (DISMISS, re.compile(r"^(?:close|dismiss|x|×|✕|✖|close banner|close dialog|close this|schlie[sß]en|fermer|cerrar|chiudi)$")),
    (ACKNOWLEDGE, re.compile(r"^(?:ok|okay|ok got it|got it|understood|i understand|fine|alright|continue)$")),
]


def normalize_label(label: str) -> str:
    text = (label or "").strip().lower()
    text = text.replace("&", " and ").replace("’", "'").replace("‘", "'")
    text = re.sub(r"[\"“”!.,:;()\[\]{}«»→›>]+", " ", text)
    text = re.sub(r"[-_/]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def classify_label(label: str) -> str:
    """Semantic action for one control's visible label. Never raises."""
    norm = normalize_label(label)
    if not norm or len(norm) > 80:
        return UNCLASSIFIED
    for action, pattern in _RULES:
        if pattern.match(norm):
            return action
    return UNCLASSIFIED


# ---- container detection ---------------------------------------------------
# CSS selectors for consent containers, most specific first. Shared with
# consent/runtime.py (rendered DOM) and consent/screenshots.py.
CONSENT_CONTAINER_SELECTORS: List[str] = [
    "#onetrust-banner-sdk", "#onetrust-pc-sdk",
    "#CybotCookiebotDialog",
    ".cky-consent-container", ".cky-modal",
    ".osano-cm-window", ".osano-cm-dialog",
    "#truste-consent-track", "#truste-consent-content", "#consent_blackbar",
    "#qc-cmp2-container", "#qc-cmp2-ui",
    "#iubenda-cs-banner",
    "#cmplz-cookiebanner-container", ".cmplz-cookiebanner",
    "#didomi-notice", "#didomi-popup", "#didomi-host",
    "#usercentrics-root", "#uc-center-container",
    "#axeptio_overlay", "#cookiefirst-root",
    "#cookie-law-info-bar", ".cli-modal",
    ".cc-window", ".cc-banner",
    ".moove-gdpr-info-bar-container", "#BorlabsCookieBox", "#tarteaucitronRoot",
    ".fc-consent-root", "[id^='sp_message_container']", "#cmpbox", "#cmpwrapper",
    "#termly-code-snippet-support",
    # generic, attribute-based
    "[role='dialog'][aria-label*='cookie' i]", "[role='dialog'][aria-label*='consent' i]",
    "[role='dialog'][aria-label*='privacy' i]", "[role='alertdialog'][aria-label*='cookie' i]",
    "[role='region'][aria-label*='cookie' i]",
    "[id*='cookie-banner' i]", "[class*='cookie-banner' i]",
    "[id*='cookiebanner' i]", "[class*='cookiebanner' i]",
    "[id*='cookie-consent' i]", "[class*='cookie-consent' i]",
    "[id*='cookieconsent' i]", "[class*='cookieconsent' i]",
    "[id*='consent-banner' i]", "[class*='consent-banner' i]",
    "[id*='cookie-notice' i]", "[class*='cookie-notice' i]",
    "[id*='cookie_notice' i]", "[id*='cookie-bar' i]", "[class*='cookie-bar' i]",
    "[id*='gdpr-banner' i]", "[class*='gdpr-banner' i]", "[id*='gdpr-consent' i]",
]

# Text that makes an element "about consent" (used for ARIA dialogs and the
# text heuristic). Kept to cookie/consent vocabulary in a few languages.
CONSENT_TEXT_PATTERN = (
    r"cookie|consent|tracking technolog|personal data|your privacy|privacy choices|"
    r"datenschutz|einwilligung|traceurs|consentement|consentimiento|consenso"
)
CONSENT_TEXT_RE = re.compile(CONSENT_TEXT_PATTERN, re.IGNORECASE)

_MAX_CONTAINER_TEXT = 4000  # an element with more text than this is a page section, not a banner
_MAX_ANCESTOR_HOPS = 8
_CLICKABLE_TAGS = ["button", "a", "input"]


@dataclass
class ConsentControl:
    """One control found inside the consent banner — the single source of truth for consent buttons."""
    label: str                       # exact visible text
    action: str                      # semantic action (see ACTION_LABELS)
    evidence: str = EVIDENCE_STATIC
    selector: Optional[str] = None   # how runtime re-locates it for clicking
    frame: str = "main"              # "main" or the iframe URL
    visible: Optional[bool] = None   # None = unknown (static markup)
    clickable: Optional[bool] = None
    layer: int = 1                   # 1 = first banner layer, 2 = preference panel
    tag: Optional[str] = None

    @property
    def action_label(self) -> str:
        return ACTION_LABELS.get(self.action, self.action)

    def as_dict(self) -> dict:
        return {
            "label": self.label, "action": self.action, "action_label": self.action_label,
            "evidence": self.evidence, "selector": self.selector, "frame": self.frame,
            "visible": self.visible, "clickable": self.clickable, "layer": self.layer, "tag": self.tag,
        }


@dataclass
class ButtonsDetection:
    # Back-compat flags/labels (consent_score and older callers read these).
    accept_found: bool = False
    reject_found: bool = False
    manage_found: bool = False
    accept_labels: List[str] = field(default_factory=list)
    reject_labels: List[str] = field(default_factory=list)
    manage_labels: List[str] = field(default_factory=list)

    # New: banner-scoped evidence.
    container_found: bool = False
    container_hint: Optional[str] = None     # selector / id / class that identified the banner
    detected_via: Optional[str] = None        # cmp_selector | aria_dialog | text_heuristic | cmp_iframe
    source: str = "static"                    # "static" | "runtime"
    controls: List[ConsentControl] = field(default_factory=list)

    @property
    def has_reject_parity(self) -> bool:
        """True when accept and reject are both offered on the first banner layer."""
        return self.accept_found and self.reject_found

    def controls_for(self, actions) -> List[ConsentControl]:
        return [c for c in self.controls if c.action in actions]

    def control_dicts(self) -> List[dict]:
        return [c.as_dict() for c in self.controls]

    @classmethod
    def from_controls(
        cls,
        controls: List[ConsentControl],
        *,
        container_found: bool,
        container_hint: Optional[str] = None,
        detected_via: Optional[str] = None,
        source: str = "static",
    ) -> "ButtonsDetection":
        det = cls(container_found=container_found, container_hint=container_hint,
                  detected_via=detected_via, source=source, controls=list(controls))
        for c in controls:
            if c.layer != 1:
                continue  # parity is judged on the first layer only
            if c.action in ACCEPT_ACTIONS:
                det.accept_found = True
                det.accept_labels.append(c.label)
            elif c.action in REJECT_ACTIONS:
                det.reject_found = True
                det.reject_labels.append(c.label)
            elif c.action in MANAGE_ACTIONS:
                det.manage_found = True
                det.manage_labels.append(c.label)
        return det


def _label_of(tag) -> str:
    text = tag.get_text(" ", strip=True) if hasattr(tag, "get_text") else ""
    if not text:
        text = tag.get("aria-label") or tag.get("value") or tag.get("title") or ""
    return re.sub(r"\s+", " ", text).strip()


def _hint_of(el) -> str:
    if el.get("id"):
        return f"#{el.get('id')}"
    classes = el.get("class") or []
    if classes:
        return el.name + "." + ".".join(classes[:3])
    return el.name or "element"


def _is_clickable_tag(tag) -> bool:
    if tag.name == "input":
        return (tag.get("type") or "").lower() in ("button", "submit")
    return tag.name in ("button", "a") or (tag.get("role") or "").lower() == "button"


def _clickables(root) -> list:
    out = []
    for tag in root.find_all(True):
        if _is_clickable_tag(tag):
            out.append(tag)
    return out


def _too_big(el) -> bool:
    return el.name in ("html", "body", "main") or len(el.get_text(" ", strip=True)) > _MAX_CONTAINER_TEXT


def detect_consent_container(soup) -> Tuple[Optional[object], Optional[str], Optional[str]]:
    """
    Locates the consent banner in static markup. Returns
    (element, detected_via, hint) or (None, None, None).
    """
    # 1. known CMP / consent selectors that actually hold a consent control
    for sel in CONSENT_CONTAINER_SELECTORS:
        try:
            matches = soup.select(sel)
        except Exception:  # noqa: BLE001 — an unsupported selector shouldn't abort detection
            continue
        for el in matches:
            if _too_big(el):
                continue
            container = el
            # A matched inner element (e.g. ".cookie-banner__text") may hold no
            # controls; climb a few levels to the element that does.
            for _ in range(3):
                if any(classify_label(_label_of(t)) in CONSENT_ACTIONS for t in _clickables(container)):
                    break
                parent = container.parent
                if parent is None or _too_big(parent):
                    break
                container = parent
            if any(classify_label(_label_of(t)) in CONSENT_ACTIONS for t in _clickables(container)):
                via = "aria_dialog" if sel.startswith("[role=") else "cmp_selector"
                return container, via, sel

    # 2. text heuristic: smallest ancestor of an accept/reject control that talks about cookies/consent
    for tag in _clickables(soup):
        action = classify_label(_label_of(tag))
        if action not in ACCEPT_ACTIONS and action not in REJECT_ACTIONS:
            continue
        node = tag.parent
        for _ in range(_MAX_ANCESTOR_HOPS):
            if node is None or getattr(node, "name", None) is None or _too_big(node):
                break
            if CONSENT_TEXT_RE.search(node.get_text(" ", strip=True)):
                return node, "text_heuristic", _hint_of(node)
            node = node.parent

    return None, None, None


def detect_buttons(page: ParsedPage) -> ButtonsDetection:
    """
    Static (raw HTML) banner-scoped detection. Controls outside the
    detected consent container are ignored entirely.
    """
    container, via, hint = detect_consent_container(page.soup)
    if container is None:
        return ButtonsDetection(container_found=False, source="static")

    controls: List[ConsentControl] = []
    seen = set()
    for tag in _clickables(container):
        label = _label_of(tag)
        if not label:
            continue
        action = classify_label(label)
        key = (label, action)
        if key in seen:
            continue
        seen.add(key)
        controls.append(ConsentControl(label=label, action=action, evidence=EVIDENCE_STATIC, tag=tag.name))

    return ButtonsDetection.from_controls(
        controls, container_found=True, container_hint=hint, detected_via=via, source="static",
    )


def check_buttons(
    page: ParsedPage,
    banner_detected: bool = True,
    detection: Optional[ButtonsDetection] = None,
) -> List[dict]:
    """
    `banner_detected=False` skips these findings entirely (banner.py's own
    "no banner" finding is the more useful one). `detection` lets the
    caller pass the runtime (rendered-banner) inventory instead of the
    static one.
    """
    if not banner_detected:
        return []

    detection = detection or detect_buttons(page)
    findings: List[dict] = []
    where = "rendered consent banner" if detection.source == "runtime" else "consent banner markup"

    if not detection.container_found:
        if detection.source == "static":
            # Client-rendered CMPs aren't in raw HTML — not a failure on its own.
            findings.append(_finding(
                "info",
                "Consent banner controls not present in static HTML",
                f"{page.url}: no consent banner container with controls was found in the raw HTML. "
                "The banner is probably rendered client-side; the live browser pass is the "
                "authoritative source for its controls.",
                recommendation="Enable the live runtime consent check to inventory the rendered banner.",
            ))
        return findings

    if detection.accept_found and not detection.reject_found:
        findings.append(_finding(
            "critical",
            "Accept button present with no equivalent reject option",
            f"{page.url}'s {where} offers {_quote(detection.accept_labels)} but no equally direct way "
            "to reject non-essential cookies on the same layer.",
            recommendation="Offer 'Reject all' (or 'Necessary only') with the same prominence and "
                            "click-depth as 'Accept all'.",
        ))
    elif not detection.accept_found and not detection.reject_found:
        labels = [c.label for c in detection.controls][:5]
        findings.append(_finding(
            "warning",
            "No recognizable accept/reject controls in consent banner",
            f"{page.url}: a consent banner was found ({detection.container_hint}) but none of its controls "
            f"read as accept or reject" + (f" (controls: {_quote(labels)})." if labels else "."),
            recommendation="Label the banner's actions clearly, e.g. 'Accept all' / 'Reject all'.",
        ))

    if (detection.accept_found or detection.reject_found) and not detection.manage_found:
        findings.append(_finding(
            "info",
            "No granular preferences/manage option found",
            f"{page.url}'s {where} offers accept/reject but no visible way to consent to "
            "individual cookie categories separately.",
            recommendation="Add a 'Manage preferences' option so visitors can opt into "
                            "specific categories (e.g. analytics but not marketing).",
        ))

    return findings


def _quote(labels: List[str]) -> str:
    return ", ".join(f"'{l}'" for l in labels[:3]) or "—"


def _finding(severity: str, title: str, description: str, recommendation: str) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
