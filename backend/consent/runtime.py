"""
consent/runtime.py

The live *behavioral* half of consent/. Every other module in this
package either reads markup (banner.py, buttons.py, preferences.py) or
watches what fires before any button is clicked (network.py). This
module is the one that actually clicks Accept / Reject / Personalize
and re-observes cookies + network traffic afterward — the only way to
confirm consent.behavior.py's verdict isn't just a banner that *looks*
compliant while doing nothing when pressed.

Implements the full runtime flow from the implementation requirements
(§4.2 "Runtime consent flow"):

    1.  clean browser context, no prior consent state
    2.  open the site
    3-5. capture cookies + network requests before consent, screenshot
         the initial banner
    6.  open Personalize/Manage Preferences, screenshot it
    7-8. click Reject, capture cookies/network after
    9-10. start a *second* clean session, click Accept, capture
          cookies/network after
    11. compare all three states and produce pass/fail findings

Reject and Accept are tested in separate browser contexts (per the
requirement doc's "clean browser context" rule in §14) so clicking one
can never contaminate the other's baseline — a single context can only
ever answer one of "what happens after Reject" or "what happens after
Accept", never both.

Same degrade-gracefully contract as the rest of consent/: any
Playwright failure (not installed, browser missing, navigation
timeout, no button found to click) yields available=False /
<state>.available=False on the affected leg rather than raising, so a
runtime failure can never take down the rest of the audit — and a leg
that couldn't run is reported as "not tested", never silently as a
pass. See consent/network.py and consent/screenshots.py for the same
pattern this mirrors.

Consent-button detection is a *two-step, container-scoped* search, not
a global scan of the page:

    Step 1 — find the consent container. Look for known CMP structures
             (OneTrust, Cookiebot, TrustArc, Didomi, etc. — matched
             dynamically off the id/class/data-* tokens a given
             vendor's widget ships with, exactly like
             consent/banner.py's static _CMP_SIGNATURES; never a single
             hardcoded site's markup) or, failing that, a generic
             element whose id/class/aria-label carries a cookie /
             consent / privacy / preference / cmp / gdpr token. See
             _find_consent_container.

    Step 2 — only *then* look for Accept / Reject / Manage inside that
             container. See _find_clickable, which now takes the
             container (or frame, while still locating the container
             itself) as its search scope, never the whole page.

This is deliberate, not incidental: a global text-match scan for words
like "OK", "Continue", "Close", "Submit" or "Done" anywhere on the
rendered page will happily click an unrelated header/login/modal
button that happens to match one of those words and has nothing to do
with cookie consent — clicking it teaches this module nothing about
the actual consent banner and can silently corrupt the before/after
comparison (e.g. "accept" resolving to a login form's "Continue"
button). Scoping every button search to a *found* consent container
first removes that whole failure class: if no consent-shaped container
exists on the rendered page, accept/reject/manage are all correctly
reported as not found, and this module makes no click at all, rather
than guessing at some other control on the page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

from config.logging import logger
from cookies.categories import ESSENTIAL, categorize_cookie
from consent.network import KNOWN_TRACKER_DOMAINS, NetworkRequest, _classify
from crawler.screenshots import DEFAULT_VIEWPORT, NAVIGATION_TIMEOUT_MS, _safe_filename, _screenshot_dir

MODULE = "consent"
CATEGORY = "runtime"

SETTLE_MS = 1_500          # idle window after page load to catch deferred trackers
CLICK_SETTLE_MS = 1_500    # idle window after a button click to catch anything it triggers
BANNER_RENDER_MS = 1_500   # wait for a client-side-rendered banner to appear before looking for buttons

# Same classification regexes as consent/buttons.py's static markup check,
# reused here to click the equivalent *rendered* element rather than just
# detect its text — kept in sync deliberately, this is the live counterpart.
# Safe to keep reasonably loose (e.g. _MANAGE_RE matching bare "Settings")
# BECAUSE they're only ever matched within an already-found consent
# container (see _find_consent_container / _find_clickable below) —
# never against the whole page, where "Settings" or "Continue" could
# just as easily belong to an account menu or a login form.
_ACCEPT_RE = re.compile(r"^\s*(accept|allow|agree)\s*(all|everything)?\s*$", re.IGNORECASE)
_REJECT_RE = re.compile(
    r"^\s*(reject|decline|deny|disagree)\s*(all)?\s*$|^\s*continue without accepting\s*$",
    re.IGNORECASE,
)
_MANAGE_RE = re.compile(
    r"^\s*(manage|customi[sz]e|preferences|cookie settings|settings|more options)\s*.*$",
    re.IGNORECASE,
)

_CLICKABLE_SELECTOR = "button, a[role='button'], a, input[type='button'], input[type='submit']"

# ---------------------------------------------------------------------------
# Step 1: consent CONTAINER detection.
#
# Known-CMP structures first — matched dynamically off the id/class/data-*
# tokens each vendor's widget actually ships with (Playwright CSS attribute
# selectors, case-insensitive via the trailing " i"), not a single site's
# markup. This list intentionally mirrors consent/banner.py's static
# _CMP_SIGNATURES (same vendors, same "known signature, generic fallback"
# shape) — banner.py reads the raw fetched HTML, this reads the *rendered*
# DOM, so a client-side-injected CMP (the common case for all of these
# vendors) is still found here even when banner.py's static pass missed it.
# (cmp key, display name, CSS selector)
_CONTAINER_CMP_SELECTORS = [
    ("onetrust", "OneTrust",
     '#onetrust-banner-sdk, #onetrust-pc-sdk, #onetrust-consent-sdk, '
     '[id*="onetrust" i], [class*="onetrust" i], [id*="optanon" i], [class*="optanon" i]'),
    ("cookiebot", "Cookiebot",
     '#CybotCookiebotDialog, [id*="cookiebot" i], [class*="cookiebot" i]'),
    ("trustarc", "TrustArc",
     '#truste-consent-track, #consent_blackbar, [id*="trustarc" i], [class*="trustarc" i], [class*="truste-" i]'),
    ("cookieyes", "CookieYes",
     '[class*="cky-consent" i], [id*="cky-consent" i], [id*="cookieyes" i], [class*="cookieyes" i]'),
    ("osano", "Osano", '[class*="osano-cm" i]'),
    ("quantcast", "Quantcast Choice", '[class*="qc-cmp" i]'),
    ("iubenda", "iubenda", '[class*="iubenda-cs" i], [class*="iub_cs" i]'),
    ("complianz", "Complianz", '[class*="cmplz-" i]'),
    ("didomi", "Didomi", '#didomi-host, [class*="didomi-" i], [id*="didomi" i]'),
]

# Generic fallback: any element whose id/class/data-testid/aria-label
# carries one of these tokens, or a dialog/banner-role element whose
# aria-label mentions one. Same token set consent/banner.py's static
# _GENERIC_MARKUP_RE looks for, translated into live CSS attribute
# selectors so a homegrown (non-CMP) banner is still found by structure
# rather than by hoping its buttons happen to match a wording pattern.
_CONTAINER_GENERIC_TOKENS = ("cookie", "consent", "privacy", "preference", "cmp", "gdpr")
_CONTAINER_GENERIC_SELECTOR = ", ".join(
    part
    for token in _CONTAINER_GENERIC_TOKENS
    for part in (
        f'[id*="{token}" i]', f'[class*="{token}" i]',
        f'[data-testid*="{token}" i]', f'[aria-label*="{token}" i]',
    )
)

# A candidate container must clear this before it's accepted, to rule
# out a stray footer link ("Cookie Policy") or a tiny icon that happens
# to carry a matching token but isn't itself the banner/dialog.
_MIN_CONTAINER_SIZE_PX = 24


@dataclass
class CookieSnapshot:
    name: str
    domain: str
    category: str  # cookies.categories.{ESSENTIAL,FUNCTIONAL,ANALYTICS,MARKETING,UNKNOWN}


@dataclass
class ConsentStateCapture:
    """Everything observed at one point in the runtime flow (before / after-reject / after-accept)."""

    available: bool = False
    cookies: List[CookieSnapshot] = field(default_factory=list)
    requests: List[NetworkRequest] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def tracker_requests(self) -> List[NetworkRequest]:
        return [r for r in self.requests if r.tracker_name]

    @property
    def non_essential_cookies(self) -> List[CookieSnapshot]:
        return [c for c in self.cookies if c.category != ESSENTIAL]


@dataclass
class ConsentRuntimeResult:
    available: bool = False
    error: Optional[str] = None

    # Step 1's result: was a consent-shaped container found on the
    # rendered page at all, before any button search was attempted?
    # False here means accept/reject/manage below were never even
    # searched for (see _find_consent_container) — a real "no banner",
    # not a button-wording miss.
    consent_container_found: bool = False
    # "onetrust" / "cookiebot" / etc. when a known CMP's structure
    # matched; None for a generic (non-CMP) container match or when no
    # container was found at all.
    consent_container_cmp: Optional[str] = None

    accept_button_found: bool = False
    reject_button_found: bool = False
    manage_button_found: bool = False

    # Authoritative "the live browser saw a consent banner" signal, derived
    # once in _derive_verdicts from what the rendered page actually showed
    # (a visible Accept or Reject control). consent_score.py reads this,
    # not the individual button flags, so the meaning lives in one place.
    # False means "not seen" — including when the pass didn't run — and
    # must never be used to *disprove* a banner the static scan found.
    banner_detected: bool = False

    accept_clicked: bool = False
    reject_clicked: bool = False
    manage_clicked: bool = False

    before_consent: ConsentStateCapture = field(default_factory=ConsentStateCapture)
    after_reject: ConsentStateCapture = field(default_factory=ConsentStateCapture)
    after_accept: ConsentStateCapture = field(default_factory=ConsentStateCapture)

    initial_banner_screenshot: Optional[str] = None
    preferences_screenshot: Optional[str] = None
    reject_screenshot: Optional[str] = None
    accept_screenshot: Optional[str] = None

    # Verdicts — None means "not tested" (button missing or Playwright
    # unavailable), and must never be treated as a pass by a caller.
    reject_blocks_tracking: Optional[bool] = None
    accept_allows_tracking: Optional[bool] = None
    personalize_exposes_controls: Optional[bool] = None

    tested_at: Optional[str] = None


async def run_consent_runtime(url: str) -> ConsentRuntimeResult:
    """
    Full §4.2 flow for one URL. Two Playwright launches are used
    internally (Reject leg, then a fresh Accept leg) so each starts
    from a genuinely clean state — see the module docstring for why
    a single context can't answer both.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("consent/runtime.py: playwright not installed — skipping consent runtime validation")
        return ConsentRuntimeResult(available=False, error="playwright not installed")

    # available starts False and is only flipped once the browser has
    # actually launched — a launch failure (Chromium missing/crashed/OOM)
    # must report as "not tested", not as a pass that happened to find
    # nothing. See models.consent's runtime_available docstring.
    result = ConsentRuntimeResult(available=False, tested_at=datetime.now(timezone.utc).isoformat())
    hostname = urlparse(url).hostname or ""

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            result.available = True
            try:
                # ---- Leg 1: before consent + Reject ------------------------------
                # Each leg is isolated in its own try/except so a failure in one
                # (e.g. a navigation timeout on the Reject leg) reports that leg
                # as "not tested" without also discarding the other, unrelated
                # leg — a single bad leg must never take the whole pass down.
                try:
                    await _run_reject_leg(browser, url, hostname, result)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"consent/runtime.py: reject leg failed for {url}: {exc}")
                    if not result.before_consent.available:
                        result.before_consent = ConsentStateCapture(available=False, error=str(exc))
                    if not result.after_reject.available:
                        result.after_reject = ConsentStateCapture(available=False, error=str(exc))

                # ---- Leg 2: fresh context, before consent again + Accept ----------
                try:
                    await _run_accept_leg(browser, url, hostname, result)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"consent/runtime.py: accept leg failed for {url}: {exc}")
                    if not result.after_accept.available:
                        result.after_accept = ConsentStateCapture(available=False, error=str(exc))
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 — a failed runtime pass should never break the audit
        # Only reachable for failures outside either leg (import already
        # succeeded above, so this is launch/context-manager level) — both
        # legs above already convert their own failures into per-leg
        # "not tested" state instead of raising this far.
        logger.warning(f"consent/runtime.py: runtime consent validation failed for {url}: {exc}")
        result.error = str(exc)

    _derive_verdicts(result)
    return result


async def _run_reject_leg(browser, url: str, hostname: str, result: ConsentRuntimeResult) -> None:
    context = await browser.new_context(viewport=DEFAULT_VIEWPORT)
    try:
        page = await context.new_page()
        captured_before: List[NetworkRequest] = []
        page.on("request", lambda r: captured_before.append(_classify(r.url, r.resource_type, hostname)))

        await page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
        await page.wait_for_timeout(max(SETTLE_MS, BANNER_RENDER_MS))

        # --- before-consent capture -----------------------------------------------
        result.before_consent = ConsentStateCapture(
            available=True,
            cookies=await _snapshot_cookies(context),
            requests=list(captured_before),
        )
        result.initial_banner_screenshot = await _capture(page, url, "consent_initial")

        # --- Step 1: find the consent container (see module docstring) -------------
        container, cmp_key = await _find_consent_container(page)
        result.consent_container_found = container is not None
        result.consent_container_cmp = cmp_key
        if container is None:
            logger.info(f"consent/runtime.py: no consent container found on {url} — skipping button search")
            result.after_reject = ConsentStateCapture(available=False, error="no consent container found")
            return

        # --- Step 2: personalize / manage preferences, scoped to that container ----
        manage_el = await _find_clickable(container, _MANAGE_RE)
        result.manage_button_found = manage_el is not None
        if manage_el is not None:
            try:
                await manage_el.click(timeout=5_000)
                await page.wait_for_timeout(CLICK_SETTLE_MS)
                result.manage_clicked = True
                result.preferences_screenshot = await _capture(page, url, "consent_preferences")
            except Exception as exc:  # noqa: BLE001
                logger.info(f"consent/runtime.py: could not click Manage/Personalize on {url}: {exc}")

            # Some CMPs (OneTrust included) open a *separate* preference-center
            # container rather than revealing more of the original banner —
            # re-resolve the container post-click so Reject is searched for in
            # whichever container is actually on screen now, falling back to
            # the original banner container when no new one appears.
            post_manage_container, _post_manage_cmp = await _find_consent_container(page)
            if post_manage_container is not None:
                container = post_manage_container

        # --- Step 2: reject, scoped to the (possibly re-resolved) container --------
        reject_el = await _find_clickable(container, _REJECT_RE)
        result.reject_button_found = reject_el is not None
        if reject_el is None:
            result.after_reject = ConsentStateCapture(available=False, error="reject button not found")
            return

        captured_after: List[NetworkRequest] = []
        page.on("request", lambda r: captured_after.append(_classify(r.url, r.resource_type, hostname)))
        try:
            await reject_el.click(timeout=5_000)
            result.reject_clicked = True
            await page.wait_for_timeout(CLICK_SETTLE_MS)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"consent/runtime.py: could not click Reject on {url}: {exc}")
            result.after_reject = ConsentStateCapture(available=False, error=str(exc))
            return

        result.after_reject = ConsentStateCapture(
            available=True,
            cookies=await _snapshot_cookies(context),
            requests=captured_after,
        )
        result.reject_screenshot = await _capture(page, url, "consent_reject")
    finally:
        await context.close()


async def _run_accept_leg(browser, url: str, hostname: str, result: ConsentRuntimeResult) -> None:
    context = await browser.new_context(viewport=DEFAULT_VIEWPORT)
    try:
        page = await context.new_page()
        await page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
        await page.wait_for_timeout(BANNER_RENDER_MS)

        # --- Step 1: find the consent container (see module docstring) -------------
        container, cmp_key = await _find_consent_container(page)
        result.consent_container_found = container is not None
        result.consent_container_cmp = cmp_key
        if container is None:
            logger.info(f"consent/runtime.py: no consent container found on {url} — skipping button search")
            result.after_accept = ConsentStateCapture(available=False, error="no consent container found")
            return

        # --- Step 2: accept, scoped to that container -------------------------------
        accept_el = await _find_clickable(container, _ACCEPT_RE)
        result.accept_button_found = accept_el is not None
        if accept_el is None:
            result.after_accept = ConsentStateCapture(available=False, error="accept button not found")
            return

        captured_after: List[NetworkRequest] = []
        page.on("request", lambda r: captured_after.append(_classify(r.url, r.resource_type, hostname)))
        try:
            await accept_el.click(timeout=5_000)
            result.accept_clicked = True
            await page.wait_for_timeout(CLICK_SETTLE_MS)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"consent/runtime.py: could not click Accept on {url}: {exc}")
            result.after_accept = ConsentStateCapture(available=False, error=str(exc))
            return

        result.after_accept = ConsentStateCapture(
            available=True,
            cookies=await _snapshot_cookies(context),
            requests=captured_after,
        )
        result.accept_screenshot = await _capture(page, url, "consent_accept")
    finally:
        await context.close()


async def _snapshot_cookies(context) -> List[CookieSnapshot]:
    raw = await context.cookies()
    return [
        CookieSnapshot(name=c["name"], domain=c.get("domain", ""), category=categorize_cookie(c["name"], c.get("domain")))
        for c in raw
    ]


async def _find_consent_container(page):
    """
    Step 1 of consent-button detection: locate the element that *is*
    the consent banner/CMP UI on the currently-loaded page, before
    looking at any button inside it.

    Tries known CMP structures first (see _CONTAINER_CMP_SELECTORS —
    matched dynamically off id/class/data-* tokens a given vendor's
    widget ships with, never a single hardcoded site's markup), then
    falls back to the generic cookie/consent/privacy/preference/cmp/gdpr
    attribute match (_CONTAINER_GENERIC_SELECTOR). Searches every frame
    attached to the page, not just the main document — a number of
    common CMPs (Sourcepoint, Quantcast/IAB TCF, Google Funding Choices)
    render their consent modal inside a child <iframe>, so a main-frame-
    only search would report no container on those sites even though a
    real visitor sees the banner fine.

    Returns (container_locator, cmp_key) — cmp_key is the matched
    vendor's key (e.g. "onetrust") or None for a generic match — or
    (None, None) when nothing consent-shaped was found anywhere on the
    rendered page. Callers MUST treat that as "no banner to test", not
    fall back to a global scan of every button on the page — that
    global-scan fallback is exactly the false-positive failure mode
    (matching an unrelated "OK"/"Continue"/"Close"/"Submit"/"Done"
    control elsewhere on the page) this two-step design exists to
    avoid; see the module docstring.
    """
    for frame in list(page.frames):
        for key, _name, selector in _CONTAINER_CMP_SELECTORS:
            container = await _first_visible_container(frame, selector)
            if container is not None:
                return container, key

    for frame in list(page.frames):
        container = await _first_visible_container(frame, _CONTAINER_GENERIC_SELECTOR)
        if container is not None:
            return container, None

    return None, None


async def _first_visible_container(frame, selector: str):
    """
    First visible, real-sized match for `selector` in `frame`, or None.
    The size floor (_MIN_CONTAINER_SIZE_PX) exists so a stray element
    that merely *carries* a matching token — a small "Cookie Policy"
    footer link, an icon-only privacy-settings button in a header — 
    isn't mistaken for the banner/dialog itself; the actual container
    is reliably a real UI surface, not a single inline link.
    """
    try:
        locator = frame.locator(selector)
        count = await locator.count()
    except Exception:  # noqa: BLE001 — a detached/cross-origin frame shouldn't abort the scan
        return None

    for i in range(min(count, 50)):  # cap: a pathological page shouldn't hang this check
        el = locator.nth(i)
        try:
            if not await el.is_visible():
                continue
            box = await el.bounding_box()
            if not box or box["width"] < _MIN_CONTAINER_SIZE_PX or box["height"] < _MIN_CONTAINER_SIZE_PX:
                continue
            return el
        except Exception:  # noqa: BLE001 — one bad element shouldn't abort the scan
            continue
    return None


async def _find_clickable(container, pattern: re.Pattern):
    """
    Step 2 of consent-button detection: returns the first visible
    element matching `pattern` by its rendered text (or aria-label/
    value for controls with no text node), or None — searched *only*
    among `container`'s descendants (a Playwright Locator, as returned
    by _find_consent_container), never the whole page. Mirrors
    consent/buttons.py's `_label_of` matching logic against *rendered*
    elements rather than static markup, since a client-side-rendered
    CMP's banner won't exist in the raw HTML consent/buttons.py reads.

    This used to search every clickable element on the page (all
    frames, no container scoping) and is deliberately narrower now —
    see the module docstring for why a global scan is the wrong design
    here (it can match an unrelated Continue/OK/Close/Submit/Done
    control that has nothing to do with cookie consent).
    """
    try:
        locator = container.locator(_CLICKABLE_SELECTOR)
        count = await locator.count()
    except Exception:  # noqa: BLE001 — a detached container shouldn't abort the scan
        return None

    for i in range(min(count, 200)):  # cap: a pathological banner shouldn't hang this check
        el = locator.nth(i)
        try:
            if not await el.is_visible():
                continue
            text = (await el.inner_text()).strip()
            if not text:
                text = (await el.get_attribute("aria-label") or await el.get_attribute("value") or "").strip()
            if text and pattern.match(text):
                return el
        except Exception:  # noqa: BLE001 — one bad element shouldn't abort the scan
            continue
    return None


async def _capture(page, url: str, hint: str) -> Optional[str]:
    out_dir = _screenshot_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_safe_filename(url)}_{hint}.png"
    try:
        await page.screenshot(path=str(out_path))
        return str(out_path)
    except Exception as exc:  # noqa: BLE001 — a failed screenshot should never break the runtime pass
        logger.warning(f"consent/runtime.py: failed to capture {hint} screenshot for {url}: {exc}")
        return None


def _derive_verdicts(result: ConsentRuntimeResult) -> None:
    """
    Translates the raw captures into the three pass/fail verdicts
    §4.3 asks for. Left as None ("not tested") whenever the underlying
    leg never ran — a missing button or a Playwright failure must
    never be reported as a pass.
    """
    # Manage/Personalize alone is deliberately not enough — too generic a
    # label ("Settings", "Manage") to prove a consent banner by itself.
    # consent_container_found is included here too: Step 1 finding a
    # consent-shaped container (by structure — CMP markup, or a generic
    # cookie/consent/privacy token) is itself real evidence a banner is
    # present, even on the rarer page where its buttons use wording
    # neither _ACCEPT_RE nor _REJECT_RE recognizes.
    result.banner_detected = bool(
        result.available
        and (result.consent_container_found or result.accept_button_found or result.reject_button_found)
    )

    if result.manage_button_found:
        result.personalize_exposes_controls = result.manage_clicked

    if result.after_reject.available:
        result.reject_blocks_tracking = (
            len(result.after_reject.tracker_requests) == 0
            and len(result.after_reject.non_essential_cookies) <= len(result.before_consent.non_essential_cookies)
        )

    if result.after_accept.available:
        # Accept "working" means the expected tracking actually turns on —
        # i.e. at least one known tracker request or a new non-essential
        # cookie appears that wasn't already present before consent.
        new_trackers = len(result.after_accept.tracker_requests) > 0
        new_cookies = len(result.after_accept.non_essential_cookies) > len(result.before_consent.non_essential_cookies)
        result.accept_allows_tracking = new_trackers or new_cookies


def check_runtime_consent(result: ConsentRuntimeResult, page_url: str) -> List[dict]:
    """Findings from an already-run ConsentRuntimeResult. Empty list when runtime data wasn't available."""
    if not result.available:
        return []

    findings: List[dict] = []

    if not result.consent_container_found:
        findings.append(_finding(
            "warning", "runtime",
            "No consent banner/CMP container found in the rendered page",
            f"{page_url}: no cookie/consent/privacy/preferences-shaped container (known CMP "
            "structure or generic markup) was found anywhere in the rendered page, so no "
            "Accept/Reject/Manage search was even attempted — this is reported separately from "
            "a button simply being unlabeled, since no click was made at all.",
            "Confirm a consent banner actually renders for a fresh visitor with no prior consent state.",
        ))

    if result.before_consent.available and result.before_consent.tracker_requests:
        names = sorted({r.tracker_name for r in result.before_consent.tracker_requests})
        findings.append(_finding(
            "critical", "runtime",
            "Trackers fire before any consent action is taken",
            f"{page_url}: {len(result.before_consent.tracker_requests)} request(s) to known "
            f"tracker(s) ({', '.join(names)}) were observed before Accept/Reject was clicked.",
            "Gate these trackers behind an explicit consent check rather than loading unconditionally.",
        ))

    if result.reject_button_found and result.reject_clicked and result.reject_blocks_tracking is False:
        findings.append(_finding(
            "critical", "runtime",
            "Reject does not stop non-essential tracking",
            f"{page_url}: after clicking Reject, tracker requests and/or non-essential cookies "
            "were still observed — the control does not do what it claims to.",
            "Ensure clicking Reject actually disables analytics/marketing scripts, not just the banner UI.",
        ))
    elif not result.reject_button_found and result.consent_container_found:
        findings.append(_finding(
            "warning", "runtime",
            "Reject button could not be located to test",
            f"{page_url}: a consent container was found, but no clickable Reject/Decline "
            "control matching recognized wording was found inside it, so this behaviour "
            "could not be runtime-verified.",
            "Confirm a reject control is rendered inside the consent banner and reachable "
            "without JavaScript errors.",
        ))

    if result.accept_button_found and result.accept_clicked and result.accept_allows_tracking is False:
        findings.append(_finding(
            "warning", "runtime",
            "Accept does not appear to enable tracking",
            f"{page_url}: after clicking Accept, no tracker requests or new non-essential "
            "cookies were observed — analytics may be broken even for consenting visitors.",
            "Verify tracking scripts actually activate after Accept is clicked (check for JS errors).",
        ))
    elif not result.accept_button_found and result.consent_container_found:
        findings.append(_finding(
            "warning", "runtime",
            "Accept button could not be located to test",
            f"{page_url}: a consent container was found, but no clickable Accept/Allow "
            "control matching recognized wording was found inside it, so this behaviour "
            "could not be runtime-verified.",
            "Confirm an accept control is rendered inside the consent banner and reachable "
            "without JavaScript errors.",
        ))

    if result.manage_button_found and not result.manage_clicked:
        findings.append(_finding(
            "info", "runtime",
            "Personalize/Manage Preferences control did not respond to a click",
            f"{page_url}: a Manage/Personalize control was found but clicking it did not "
            "appear to open a preference interface.",
            "Verify the control opens a working preference panel.",
        ))

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
