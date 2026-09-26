"""
consent/cookies.py

Thin bridge between the standalone cookies/ package (detector,
categories, expiry, validator, storage — none of which know anything
about consent banners) and the rest of consent/: runs
cookies.run_cookie_checks and additionally cross-references each
cookie's category against consent timing — both halves of it:

  Before consent  — what's already sitting in the jar (or, absent a
                    live browser pass, what the server set in its
                    initial response) before the visitor has made any
                    choice at all, broken down by category: analytics,
                    advertising/marketing, functional, and unknown.
  After Reject All — once the visitor has explicitly rejected
                    everything non-essential, does anything
                    non-essential remain?

Kept separate from cookies/storage.py on purpose: storage.py's
build_cookie_summary has no concept of "consent", so it stays reusable
outside this audit module; the consent-timing cross-reference belongs
here instead.

Important, and worth stating plainly since it's easy to get wrong: a
non-essential cookie being *present* is not, by itself, a GDPR
violation. Whether it's a violation depends on:

    cookie detected + cookie classification + consent state
    + applicable region  =  compliance result

Detection and classification are this module's job (and cookies/
categories.py's). Consent state — before any action, or after Reject
All was actually clicked — comes from consent.runtime's live capture.
Applicable region is resolved by consent.consent_score.
resolve_applicable_frameworks. The actual pass/fail *compliance*
verdict is assembled from all four in
consent.consent_score.build_gdpr_assessment (see
_cookies_before_consent_check there for the before-consent verdict);
this module never renders that verdict itself — the functions below
only report what was observed. Two things in particular this module
refuses to assume:

  - An UNKNOWN-category cookie (not recognized by cookies/categories.py's
    lookup table) is reported separately from, and at lower confidence
    than, a cookie in a *known* non-essential category — it might turn
    out to be essential once someone actually checks it. See
    cookies/categories.py's own docstring on why "unknown" is left
    unguessed rather than defaulted either way.
  - A region this audit isn't actually subject to (e.g. GDPR checks on
    a site with no EU/EEA/UK/Switzerland relevance) doesn't get graded
    against these findings at all — that gating lives in
    consent.consent_score, not here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from crawler.parser import ParsedPage

from cookies.categories import ANALYTICS, ESSENTIAL, FUNCTIONAL, MARKETING, UNKNOWN, categorize_cookie, display_name
from cookies.detector import Cookie
from cookies.storage import CookieAuditResult, run_cookie_checks

if TYPE_CHECKING:  # avoid importing consent.runtime (Playwright-adjacent) at module load time
    from consent.runtime import CookieSnapshot, ConsentRuntimeResult

MODULE = "consent"
CATEGORY = "cookies"

# The four buckets a consent banner is supposed to let a visitor opt
# in/out of independently, excluding ESSENTIAL — these are the
# categories "Before consent" analysis breaks cookies down into.
_TRACKED_CATEGORIES = (ANALYTICS, MARKETING, FUNCTIONAL, UNKNOWN)
# Of those, the ones a lookup-table match actually recognizes as
# non-essential (as opposed to merely "we don't know") — used to keep
# "known tracker" findings separate from "unclassified, needs review".
_KNOWN_NON_ESSENTIAL = (ANALYTICS, MARKETING, FUNCTIONAL)


def analyze_cookies(
    cookies: List[Cookie],
    page: Optional[ParsedPage] = None,
    first_party_hostname: Optional[str] = None,
    blocks_scripts_pre_consent: Optional[bool] = None,
    runtime_result: Optional["ConsentRuntimeResult"] = None,
) -> CookieAuditResult:
    """
    Runs the full cookies/ package pipeline, then layers on the
    before/after-consent cross-reference:

    - When a pre-consent verdict is available from
      consent.behavior.evaluate_behavior (`blocks_scripts_pre_consent`)
      and it says scripts *aren't* held back, adds a finding for
      non-essential cookies seen in the page's initial HTTP response —
      see check_pre_consent_cookies for that finding's real scope
      (Set-Cookie headers only, no timing guarantee).

    - When a live `runtime_result` (consent.runtime.run_consent_runtime's
      output) is supplied, adds the two timing-aware checks this
      module can't do from static headers alone: a before-consent
      category breakdown (check_cookies_before_consent) and an
      after-Reject-All non-essential-cookie check
      (check_cookies_after_reject). Both degrade to "no findings" —
      never a guessed pass or fail — when the relevant leg of the
      runtime pass didn't run; see each function's own docstring.
    """
    result = run_cookie_checks(cookies, page=page, first_party_hostname=first_party_hostname)

    if blocks_scripts_pre_consent is False:
        result.findings += check_pre_consent_cookies(cookies)

    if runtime_result is not None:
        result.findings += check_cookies_before_consent(runtime_result)
        result.findings += check_cookies_after_reject(runtime_result)

    return result


def check_pre_consent_cookies(cookies: List[Cookie]) -> List[dict]:
    """
    Flags non-essential cookies seen in the *initial HTTP response*
    (Set-Cookie headers from a single fetch) on a page whose scripts
    aren't confirmed to be held back pre-consent.

    Scope, stated plainly: this is detection + classification of what the
    server sent, not a before/after-consent timing measurement. It can't
    see cookies set later by JavaScript (most analytics/advertising ones)
    and says nothing about consent state. The authoritative "were
    non-essential cookies present before consent?" verdict is
    consent.runtime's before-consent snapshot (see check_cookies_before_consent
    below, and consent_score._cookies_before_consent_check, which uses
    the same snapshot to decide the GDPR compliance check); this
    finding is the response-header complement to it.
    """
    non_essential = [c for c in cookies if categorize_cookie(c.name, c.domain) != ESSENTIAL]
    if not non_essential:
        return []

    names = ", ".join(sorted({c.name for c in non_essential})[:5])
    return [{
        "module": MODULE,
        "category": CATEGORY,
        "severity": "critical",
        "title": "Non-essential cookies set in the initial HTTP response",
        "description": f"{len(non_essential)} non-essential cookie(s) ({names}) were set by the server "
                        "in the page's initial response, on a site where scripts aren't confirmed to be "
                        "held back until consent. (Server-set cookies only — cookies set later by "
                        "JavaScript aren't visible to this check.)",
        "recommendation": "Confirm these cookies are only set after the visitor consents to "
                           "the relevant category, not unconditionally on page load.",
    }]


def classify_cookie_snapshots(cookies: List["CookieSnapshot"]) -> Dict[str, List["CookieSnapshot"]]:
    """
    Groups a runtime cookie snapshot (consent.runtime.CookieSnapshot,
    already carrying its category from cookies.categories.categorize_cookie)
    by category. Every category — ESSENTIAL plus the four tracked in
    this module — is always present as a key, even with an empty list,
    so a caller can report "0 advertising/marketing cookies" instead of
    a missing key.
    """
    buckets: Dict[str, List["CookieSnapshot"]] = {c: [] for c in (ESSENTIAL,) + _TRACKED_CATEGORIES}
    for cookie in cookies:
        buckets.setdefault(cookie.category, []).append(cookie)
    return buckets


def summarize_before_consent(
    runtime_result: Optional["ConsentRuntimeResult"],
) -> Optional[Dict[str, List["CookieSnapshot"]]]:
    """
    The before-consent category breakdown: every cookie sitting in the
    jar in a fresh browser context, page loaded, *before* any consent
    action is taken — the same snapshot consent_score.
    _cookies_before_consent_check judges the GDPR
    cookies_blocked_pre_consent check from — grouped by category
    (analytics / advertising-marketing / functional / unknown /
    essential).

    Returns None, not an empty dict, when the runtime pass didn't run
    or couldn't capture the before-consent snapshot — "we don't know"
    must never collapse into "zero cookies found".
    """
    before = runtime_result.before_consent if runtime_result else None
    if not (runtime_result and runtime_result.available and before and before.available):
        return None
    return classify_cookie_snapshots(before.cookies)


def check_cookies_before_consent(runtime_result: Optional["ConsentRuntimeResult"]) -> List[dict]:
    """
    "Before consent" cookie analysis: reports which non-essential
    categories — analytics, advertising/marketing, functional,
    unknown — were actually observed before the visitor made any
    consent choice.

    Deliberately informational (severity "info"), not a pass/fail
    verdict: presence before consent is exactly the fact pattern GDPR's
    opt-in model cares about, but whether it's *non-compliant* also
    depends on which regional framework applies to this audit — see the
    module docstring's compliance formula. That region-aware verdict is
    consent.consent_score.build_gdpr_assessment's
    cookies_blocked_pre_consent check; this finding is the descriptive
    counterpart, always present when there's something to describe,
    independent of region.

    Returns [] when the runtime pass didn't capture a before-consent
    snapshot, or when nothing non-essential was found in it.
    """
    breakdown = summarize_before_consent(runtime_result)
    if breakdown is None:
        return []

    counts = {cat: len(breakdown[cat]) for cat in _TRACKED_CATEGORIES if breakdown[cat]}
    if not counts:
        return []

    parts = ", ".join(f"{n} {display_name(cat).lower()}" for cat, n in sorted(counts.items()))
    return [{
        "module": MODULE,
        "category": CATEGORY,
        "severity": "info",
        "title": "Cookie categories present before consent",
        "description": f"Before any consent action was taken, cookies were observed in these "
                        f"non-essential categories: {parts}. Presence alone isn't a violation on its "
                        "own — see this audit's GDPR/UK GDPR/Swiss FADP breakdown (when applicable to "
                        "this site's region) for the actual compliance verdict.",
        "recommendation": "Confirm each category listed here is genuinely gated behind consent rather "
                           "than loaded unconditionally on page load.",
    }]


def check_cookies_after_reject(runtime_result: Optional["ConsentRuntimeResult"]) -> List[dict]:
    """
    "After Reject All" cookie analysis: with the visitor having
    explicitly clicked Reject, does anything outside the ESSENTIAL
    category still sit in the jar?

    This is related to, but stricter and simpler than,
    consent.runtime's own reject_blocks_tracking verdict —
    reject_blocks_tracking compares the after-reject count against the
    before-consent baseline (did Reject *reduce* tracking?); this check
    asks only whether anything non-essential is left *at all*,
    regardless of what was there before Reject was clicked.

    Deliberately not a blanket "any non-essential cookie present after
    Reject = GDPR violation" rule — see the module docstring:

      - runs only when the Reject leg actually completed: the runtime
        pass launched, Reject was actually clicked, and an after-reject
        snapshot was captured. A leg that never ran reports nothing —
        never a guessed pass or fail.
      - cookies in a *known* non-essential category (analytics,
        advertising/marketing, functional) are reported separately from
        UNKNOWN-category ones, and at a different severity: a known
        category left behind after Reject is a clear, critical finding;
        an unrecognized cookie is flagged as needing manual review
        rather than asserted as non-essential, since it might turn out
        to be essential once someone actually checks it.
      - whether this is a compliance failure still depends on which
        regional framework applies to this audit — that gating happens
        in consent.consent_score, not here; this function only reports
        what the live browser observed.
    """
    if runtime_result is None or not runtime_result.available:
        return []
    if not runtime_result.reject_clicked:
        return []

    after = runtime_result.after_reject
    if not after.available:
        return []

    remaining = after.non_essential_cookies
    if not remaining:
        return []

    buckets = classify_cookie_snapshots(remaining)
    known = [c for cat in _KNOWN_NON_ESSENTIAL for c in buckets[cat]]
    unknown = buckets[UNKNOWN]

    findings: List[dict] = []

    if known:
        counts: Dict[str, int] = {}
        for cookie in known:
            counts[cookie.category] = counts.get(cookie.category, 0) + 1
        breakdown = ", ".join(f"{n} {display_name(cat).lower()}" for cat, n in sorted(counts.items()))
        names = ", ".join(sorted({c.name for c in known})[:5])
        findings.append({
            "module": MODULE,
            "category": CATEGORY,
            "severity": "critical",
            "title": "Non-essential cookies remain after Reject All",
            "description": f"After clicking Reject All, {len(known)} cookie(s) outside the "
                            f"strictly-necessary category were still present ({breakdown}: {names}).",
            "recommendation": "Stop setting, or actively clear, these cookies once the visitor has "
                               "rejected the relevant category — Reject All should mean everything "
                               "non-essential stops, not just the banner disappearing.",
        })

    if unknown:
        names = ", ".join(sorted({c.name for c in unknown})[:5])
        findings.append({
            "module": MODULE,
            "category": CATEGORY,
            "severity": "warning",
            "title": "Unclassified cookies remain after Reject All",
            "description": f"After clicking Reject All, {len(unknown)} cookie(s) not recognized by this "
                            f"audit's category lookup were still present ({names}). They may turn out to "
                            "be essential (and fine to keep) or non-essential (and a compliance gap) — "
                            "this couldn't be determined automatically.",
            "recommendation": "Manually confirm the purpose of these cookies and, if non-essential, "
                               "ensure they're cleared when consent is rejected.",
        })

    return findings
