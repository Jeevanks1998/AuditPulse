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

    accept_button_found: bool = False
    reject_button_found: bool = False
    manage_button_found: bool = False

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

    result = ConsentRuntimeResult(available=True, tested_at=datetime.now(timezone.utc).isoformat())
    hostname = urlparse(url).hostname or ""

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                # ---- Leg 1: before consent + Reject -----------------------------------
                await _run_reject_leg(browser, url, hostname, result)
                # ---- Leg 2: fresh context, before consent again + Accept --------------
                await _run_accept_leg(browser, url, hostname, result)
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 — a failed runtime pass should never break the audit
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

        # --- personalize / manage preferences --------------------------------------
        manage_el = await _find_clickable(page, _MANAGE_RE)
        result.manage_button_found = manage_el is not None
        if manage_el is not None:
            try:
                await manage_el.click(timeout=5_000)
                await page.wait_for_timeout(CLICK_SETTLE_MS)
                result.manage_clicked = True
                result.preferences_screenshot = await _capture(page, url, "consent_preferences")
            except Exception as exc:  # noqa: BLE001
                logger.info(f"consent/runtime.py: could not click Manage/Personalize on {url}: {exc}")

        # --- reject ------------------------------------------------------------------
        reject_el = await _find_clickable(page, _REJECT_RE)
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

        accept_el = await _find_clickable(page, _ACCEPT_RE)
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


async def _find_clickable(page, pattern: re.Pattern):
    """
    Returns the first visible element matching `pattern` by its
    rendered text (or aria-label/value for controls with no text
    node), or None. Mirrors consent/buttons.py's `_label_of` matching
    logic against *rendered* elements rather than static markup, since
    a client-side-rendered CMP's banner won't exist in the raw HTML
    consent/buttons.py reads.
    """
    locator = page.locator(_CLICKABLE_SELECTOR)
    try:
        count = await locator.count()
    except Exception:  # noqa: BLE001
        return None

    for i in range(min(count, 200)):  # cap: a pathological page shouldn't hang this check
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
    elif not result.reject_button_found:
        findings.append(_finding(
            "warning", "runtime",
            "Reject button could not be located to test",
            f"{page_url}: no clickable Reject/Decline control was found in the rendered page, "
            "so this behaviour could not be runtime-verified.",
            "Confirm a reject control is rendered and reachable without JavaScript errors.",
        ))

    if result.accept_button_found and result.accept_clicked and result.accept_allows_tracking is False:
        findings.append(_finding(
            "warning", "runtime",
            "Accept does not appear to enable tracking",
            f"{page_url}: after clicking Accept, no tracker requests or new non-essential "
            "cookies were observed — analytics may be broken even for consenting visitors.",
            "Verify tracking scripts actually activate after Accept is clicked (check for JS errors).",
        ))
    elif not result.accept_button_found:
        findings.append(_finding(
            "warning", "runtime",
            "Accept button could not be located to test",
            f"{page_url}: no clickable Accept/Allow control was found in the rendered page, "
            "so this behaviour could not be runtime-verified.",
            "Confirm an accept control is rendered and reachable without JavaScript errors.",
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
