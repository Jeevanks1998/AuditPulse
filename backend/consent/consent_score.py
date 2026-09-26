"""
consent/consent_score.py

Turns the flat finding lists every other consent/* module returns into
a single weighted 0-100 score with a per-category breakdown — same
shape Audit.breakdown["consent"] / AuditStatsOut.breakdown already
carry for the other modules (see analytics/analytics_score.py,
seo/seo_score.py for the identical pattern this mirrors).

Also exposes `build_consent_summary`, which assembles a
models.consent.Consent-ready row from every consent/* + cookies/*
detection in one place — this is what
services.audit_service._write_consent_result should build from once
it's wired to the real checks instead of its current
random.randint(...) placeholder.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from crawler.parser import ParsedPage

from consent.behavior import BehaviorResult
from consent.buttons import ButtonsDetection
from consent.ccpa import CcpaLinkDetection, detect_gpc_handling, detect_privacy_choices_link
from consent.consent_mode import ConsentModeDetection
from consent.preferences import PreferencesDetection
from cookies.storage import CookieSummary

if TYPE_CHECKING:  # avoid importing consent.runtime / consent.region_detector at module load time
    from consent.runtime import ConsentRuntimeResult
    # consent.region_detector imports resolve_applicable_frameworks from
    # *this* module, so a real (non-TYPE_CHECKING) import here would be
    # circular — this annotation-only import is safe because
    # `from __future__ import annotations` makes it a string at runtime.
    from consent.region_detector import RegionDetectionResult
    from consent.network import PreConsentNetworkResult

MODULE = "consent"

SEVERITY_PENALTY = {"critical": 30, "warning": 15, "info": 5}

# Must sum to 1.0. Categories not listed here (e.g. an unrecognized
# `category` value on a finding) are folded into "other" at a small
# default weight so nothing is silently dropped from the overall score.
CATEGORY_WEIGHTS: Dict[str, float] = {
    "banner": 0.25,        # no banner at all is the single biggest compliance gap
    "buttons": 0.15,
    "behavior": 0.20,      # scripts actually held back pre-consent — the substance behind the banner
    "network": 0.10,
    "cookies": 0.15,
    "consent_mode": 0.05,
    "preferences": 0.10,
}

_OTHER_CATEGORY = "other"
_OTHER_WEIGHT = 0.05

_PRIVACY_POLICY_LINK_RE = re.compile(r"privacy (policy|notice)", re.IGNORECASE)
_PRIVACY_POLICY_HREF_RE = re.compile(r"privacy[-_]?(policy|notice)", re.IGNORECASE)

# Rough CCPA signal: a "Do Not Sell/Share My Personal Information" link
# (required verbatim-ish wording under CCPA/CPRA for businesses that sell data).
_CCPA_LINK_RE = re.compile(r"do not sell (or share )?my (personal )?information", re.IGNORECASE)

# ---------------------------------------------------------------------------
# lawful_consent_controls signals (GDPR).
#
# GDPR's Art. 4(11)/Recital 32 affirmative-action requirement rules out
# two specific patterns, both of which are still common on the open web:
# a non-essential category checkbox that starts pre-checked (opt-out by
# default instead of opt-in), and "by continuing to browse/use this site
# you agree/consent" copy, which CNIL/ICO guidance is explicit can never
# itself constitute valid consent — only a real affirmative click can.
# Both are detectable statically, no runtime pass required.
_NON_ESSENTIAL_CATEGORY_RE = re.compile(
    r"analytics|marketing|advertis|performance|targeting|social media|personali[sz]ation",
    re.IGNORECASE,
)
_IMPLIED_CONSENT_RE = re.compile(
    r"by\s+(continuing|browsing|using)\s+(to\s+(browse|use)\s+)?(this\s+)?(site|website|page)?"
    r"[^.]{0,60}?(you\s+)?(agree|consent|accept)"
    r"|continu(?:ed|ing)\s+(?:to\s+)?(?:browse|use)\s+(?:this\s+)?(?:site|website)"
    r"[^.]{0,60}?(?:constitutes|indicates|means)\s+(?:your\s+)?(?:consent|agreement|acceptance)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# consent_state_persistence signal (GDPR).
#
# Recognizable cookie-name fragments for the major CMPs' own
# consent-state cookies (OneTrust's OptanonConsent, Cookiebot's
# CookieConsent, Didomi's token, TrustArc, etc.) plus generic
# "cookie_consent"/"consent_state"-style names a homegrown banner might
# use. Not exhaustive — same "known signature, generic fallback" caveat
# as consent/banner.py's CMP list — so a genuine miss here is a signal
# to verify manually, not an absolute "never persists".
_CONSENT_STATE_COOKIE_RE = re.compile(
    r"cookieconsent|cookie[-_]?consent|consent[-_]?state|onetrust|optanon|cookiebot|cybotcookiebot|"
    r"didomi|trustarc|truste|cmpconsent|euconsent|cookieyes|cky-consent|gdpr[-_]?consent|consentmanager",
    re.IGNORECASE,
)


def _checkbox_label_text(page: ParsedPage, checkbox) -> str:
    """Best-effort label text for a checkbox: aria-label, an associated
    <label for=id>, a wrapping <label>, or (failing those) the nearby
    parent element's text, in that preference order."""
    parts: List[str] = []
    aria = checkbox.get("aria-label")
    if aria:
        parts.append(aria)
    checkbox_id = checkbox.get("id")
    if checkbox_id:
        label_tag = page.soup.find("label", attrs={"for": checkbox_id})
        if label_tag:
            parts.append(label_tag.get_text(" ", strip=True))
    wrapping_label = checkbox.find_parent("label")
    if wrapping_label:
        parts.append(wrapping_label.get_text(" ", strip=True))
    if not parts:
        parent = checkbox.find_parent()
        if parent is not None:
            parts.append(parent.get_text(" ", strip=True)[:120])
    return " ".join(p for p in parts if p)


def _detect_preticked_nonessential_checkboxes(page: ParsedPage) -> List[str]:
    """
    Finds checkbox inputs that are pre-checked (a `checked` attribute is
    present) AND whose label text names an optional/non-essential cookie
    category (analytics, marketing, advertising, etc.). "Necessary"/
    "essential" checkboxes are routinely pre-checked and disabled by
    design (visitors can't turn them off at all), so this deliberately
    only flags boxes for a category that's actually supposed to be a
    real choice.
    """
    hits: List[str] = []
    for checkbox in page.soup.find_all("input", attrs={"type": re.compile("^checkbox$", re.IGNORECASE)}):
        if not checkbox.has_attr("checked"):
            continue
        label_text = _checkbox_label_text(page, checkbox)
        if label_text and _NON_ESSENTIAL_CATEGORY_RE.search(label_text):
            hits.append(label_text.strip())
    return hits


def _detect_implied_consent_language(text: str) -> Optional[str]:
    """
    Looks for "by continuing to browse/use this site you agree/consent"
    style phrasing anywhere in the page's visible text. Returns the
    matched snippet (trimmed, for use in a check's detail text) or None.
    """
    match = _IMPLIED_CONSENT_RE.search(text or "")
    if not match:
        return None
    start = max(0, match.start() - 10)
    end = min(len(text), match.end() + 10)
    return re.sub(r"\s+", " ", text[start:end]).strip()


# ---------------------------------------------------------------------------
# Region -> applicable regional framework
#
# GDPR and CCPA/CPRA used to both be evaluated on every audit regardless of
# where the audited site is actually subject to either of them. That's wrong
# on two counts: a US-only site got graded (and could "fail") against GDPR
# checks that were never legally relevant to it, and a region we simply
# couldn't determine ("unknown") was silently treated the same as "assessed
# and non-compliant" instead of "no verdict".
#
# The table this module now follows:
#
#   Detected region      Assessment
#   ------------------   ------------------------------------------------
#   EU / EEA              GDPR
#   UK                     UK GDPR
#   Switzerland            Swiss FADP
#   California             CCPA / CPRA
#   Other US               CCPA only if California applicability is
#                          detected/configured (CCPA applies by who a
#                          business serves, not just where it's based)
#   Unknown                No regional compliance verdict (neither
#                          framework — this is NOT a failure)
#
# GDPR, UK GDPR and Swiss FADP all share the same opt-in-consent model that
# GDPR_CHECK_ORDER already tests for, so one framework-agnostic assessment
# covers all three; only the display name changes per region.
# ---------------------------------------------------------------------------

# Recognized region codes. Whatever upstream region-detection step feeds
# `region` into build_consent_summary (geo-IP, ccTLD, configured target
# market — not this module's concern) is expected to normalize onto one of
# these; anything else is treated as REGION_UNKNOWN, never guessed at.
REGION_EU = "EU"
REGION_EEA = "EEA"
REGION_UK = "UK"
REGION_SWITZERLAND = "CH"
REGION_US_CALIFORNIA = "US-CA"
REGION_US_OTHER = "US"
REGION_UNKNOWN = "UNKNOWN"

_REGION_ALIASES: Dict[str, str] = {
    "EU": REGION_EU,
    "EEA": REGION_EEA,
    "UK": REGION_UK,
    "GB": REGION_UK,
    "CH": REGION_SWITZERLAND,
    "SWITZERLAND": REGION_SWITZERLAND,
    "US-CA": REGION_US_CALIFORNIA,
    "CA": REGION_US_CALIFORNIA,
    "CALIFORNIA": REGION_US_CALIFORNIA,
    "US": REGION_US_OTHER,
    "US-OTHER": REGION_US_OTHER,
}

# Display name for the GDPR-family framework that applies in each region —
# same ten GDPR_CHECK_ORDER checks underneath, different label on the report.
_GDPR_FAMILY_FRAMEWORK_NAME: Dict[str, str] = {
    REGION_EU: "GDPR",
    REGION_EEA: "GDPR",
    REGION_UK: "UK GDPR",
    REGION_SWITZERLAND: "Swiss FADP",
}


@dataclass(frozen=True)
class ApplicableFrameworks:
    """
    Which single regional framework, if any, this audit should be judged
    against — resolved once from the detected region so GDPR and CCPA are
    each only assessed when actually relevant, instead of both running
    unconditionally on every audit.
    """
    region: str                        # normalized region code, or REGION_UNKNOWN
    assess_gdpr: bool                  # True for EU/EEA, UK, Switzerland
    gdpr_framework_name: Optional[str] # "GDPR" / "UK GDPR" / "Swiss FADP", else None
    assess_ccpa: bool                  # True for California, or Other-US with CA applicability


def resolve_applicable_frameworks(
    region: Optional[str],
    *,
    california_applicability: Optional[bool] = None,
) -> ApplicableFrameworks:
    """
    Maps a detected region straight onto the one regional framework that
    applies to this audit, per the table at the top of this section.

    `region` is whatever the site's region-detection step determined
    (case-insensitive; unrecognized values fall back to REGION_UNKNOWN,
    same as `region=None`) — detecting the region itself is out of scope
    for this module.

    `california_applicability` is an explicit signal (detected — e.g. the
    site is known to serve California residents — or manually configured
    on the audit's target market) that a non-California US site is still
    subject to CCPA/CPRA. CCPA applies based on who a business does
    business with, not just where it's headquartered, so this is left as
    an explicit opt-in rather than assumed: with no signal at all, "Other
    US" gets no CCPA verdict, matching the table above.

    Unknown always resolves to neither framework — never a failure, just
    no regional compliance verdict, so callers must treat
    GdprAssessment.compliant / CcpaAssessment.compliant of None as "not
    assessed", not as "non-compliant".
    """
    normalized = _REGION_ALIASES.get((region or "").strip().upper(), REGION_UNKNOWN)

    if normalized in _GDPR_FAMILY_FRAMEWORK_NAME:
        return ApplicableFrameworks(
            region=normalized,
            assess_gdpr=True,
            gdpr_framework_name=_GDPR_FAMILY_FRAMEWORK_NAME[normalized],
            assess_ccpa=False,
        )

    if normalized == REGION_US_CALIFORNIA:
        return ApplicableFrameworks(normalized, assess_gdpr=False, gdpr_framework_name=None, assess_ccpa=True)

    if normalized == REGION_US_OTHER:
        return ApplicableFrameworks(
            normalized, assess_gdpr=False, gdpr_framework_name=None,
            assess_ccpa=bool(california_applicability),
        )

    # REGION_UNKNOWN (or anything else unrecognized): no regional verdict.
    return ApplicableFrameworks(REGION_UNKNOWN, assess_gdpr=False, gdpr_framework_name=None, assess_ccpa=False)


@dataclass
class ConsentScoreResult:
    overall: int
    breakdown: Dict[str, int] = field(default_factory=dict)
    counts_by_severity: Dict[str, int] = field(default_factory=dict)
    findings: List[dict] = field(default_factory=list)


def score_consent(findings: List[dict]) -> ConsentScoreResult:
    """
    Scores a flat list of finding dicts (as returned by
    consent.run_page_checks, or concatenated across an entire crawl)
    into an overall score plus per-category breakdown.
    """
    by_category: Dict[str, List[dict]] = {}
    for finding in findings:
        category = finding.get("category") or _OTHER_CATEGORY
        by_category.setdefault(category, []).append(finding)

    breakdown: Dict[str, int] = {}
    weight_total = 0.0
    weighted_sum = 0.0

    all_categories = set(CATEGORY_WEIGHTS) | set(by_category)
    for category in all_categories:
        weight = CATEGORY_WEIGHTS.get(category, _OTHER_WEIGHT)
        score = _score_category(by_category.get(category, []))
        breakdown[category] = score
        weight_total += weight
        weighted_sum += score * weight

    overall = round(weighted_sum / weight_total) if weight_total else 100

    counts_by_severity: Dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
    for finding in findings:
        severity = finding.get("severity", "info")
        counts_by_severity[severity] = counts_by_severity.get(severity, 0) + 1

    return ConsentScoreResult(
        overall=overall,
        breakdown=breakdown,
        counts_by_severity=counts_by_severity,
        findings=findings,
    )


def _score_category(category_findings: List[dict]) -> int:
    score = 100
    for finding in category_findings:
        score -= SEVERITY_PENALTY.get(finding.get("severity", "info"), SEVERITY_PENALTY["info"])
    return max(0, score)


# The twelve individual technical checks that make up a GDPR assessment,
# in display order. Each maps to one specific, independently-testable
# requirement rather than being folded into a single pass/fail bit —
# see GdprAssessment below for why that distinction matters.
GDPR_CHECK_ORDER = (
    "consent_banner",
    "lawful_consent_controls",
    "accept_control",
    "reject_control",
    "reject_parity",
    "trackers_blocked_pre_consent",
    "cookies_blocked_pre_consent",
    "consent_is_granular",
    "consent_withdrawal_available",
    "privacy_policy_available",
    "consent_state_persistence",
    "reject_blocks_tracking",
)

GDPR_CHECK_LABELS: Dict[str, str] = {
    "consent_banner": "Consent banner",
    "lawful_consent_controls": "Lawful consent controls (affirmative opt-in, no pre-ticked boxes)",
    "accept_control": "Accept control",
    "reject_control": "Reject control",
    "reject_parity": "Reject parity",
    "trackers_blocked_pre_consent": "Non-essential trackers blocked before consent",
    "cookies_blocked_pre_consent": "Non-essential cookies blocked before consent",
    "consent_is_granular": "Consent is granular",
    "consent_withdrawal_available": "Consent withdrawal available",
    "privacy_policy_available": "Privacy policy available",
    "consent_state_persistence": "Consent choice persists across visits",
    "reject_blocks_tracking": "Reject actually blocks tracking (analytics behavior after rejection)",
}

# "reject_blocks_tracking" and "consent_state_persistence" are deliberately
# excluded: both depend on the optional Playwright runtime pass (a live
# accept/reject click-through), so they're routinely None ("not tested")
# on a static-only audit — counting an untested check as a failure would
# make every such audit non-compliant regardless of what the banner
# itself actually does. See RegionalScoringProfile.required_for_compliance.
_REQUIRED_FOR_COMPLIANCE = frozenset(GDPR_CHECK_ORDER) - {"reject_blocks_tracking", "consent_state_persistence"}


@dataclass(frozen=True)
class RegionalScoringProfile:
    """
    One named regional compliance profile: the full ordered set of
    checks it scores an audit against, their display labels, and which
    of those checks are excluded from the pass/fail compliance verdict
    because they depend on the optional Playwright runtime pass (and so
    are routinely "not tested" on a static-only audit).

    GDPR_PROFILE and CCPA_PROFILE (defined once each profile's checks
    exist below) are the two canonical profiles this module evaluates —
    see REGIONAL_SCORING_PROFILES for both keyed together, and
    resolve_applicable_frameworks for which single profile (if any)
    applies to a given audit's detected region. GDPR_CHECK_ORDER/
    GDPR_CHECK_LABELS and CCPA_CHECK_ORDER/CCPA_CHECK_LABELS remain the
    source of truth build_gdpr_assessment/build_ccpa_assessment read
    from directly; this wraps them into one discoverable object for
    anything else (this module's own _REQUIRED_FOR_COMPLIANCE constants,
    or a report that wants to introspect "what does this profile check")
    that wants both profiles addressable the same way instead of four
    separately-named module constants.
    """
    name: str
    check_order: tuple
    check_labels: Dict[str, str]
    runtime_only_checks: frozenset = field(default_factory=frozenset)

    @property
    def required_for_compliance(self) -> frozenset:
        return frozenset(self.check_order) - self.runtime_only_checks


# framework_name below is the profile's default display name; individual
# GDPR-family audits override it per region ("GDPR" / "UK GDPR" / "Swiss
# FADP" — see build_gdpr_assessment's framework_name param), since all
# three share this exact same set of checks.
GDPR_PROFILE = RegionalScoringProfile(
    name="GDPR",
    check_order=GDPR_CHECK_ORDER,
    check_labels=GDPR_CHECK_LABELS,
    runtime_only_checks=frozenset({"reject_blocks_tracking", "consent_state_persistence"}),
)


@dataclass
class GdprCheck:
    key: str
    label: str
    passed: Optional[bool]  # None = not evaluated (missing data, e.g. runtime pass didn't run)
    detail: str = ""
    # Structured, UI-renderable evidence backing a failed check — e.g. the
    # actual tracker requests seen for trackers_blocked_pre_consent. Only
    # populated for checks that have real underlying evidence data to show
    # (currently just trackers_blocked_pre_consent, from the live
    # consent.network pre-consent capture); every other check has to make
    # do with `detail` alone. Shape: {"summary": str, "items": [str, ...],
    # "items_label": str}. `items`/`items_label` are omitted (left as an
    # empty list / "") when there's nothing list-like to show.
    evidence: Optional[dict] = None


@dataclass
class GdprAssessment:
    """
    The individual-signal replacement for a single `gdpr_compliant`
    boolean. "GDPR compliant = TRUE/FALSE" hides *which* requirement a
    site fails; a banner with an accept-only button and one that blocks
    trackers correctly but has no reject control at all both used to
    collapse to the same `False`. Each check here maps to one distinct
    technical requirement (a clear positive action, no non-essential
    cookies before consent, an equally-easy way to withdraw, etc.) so a
    report can say exactly which one is missing.
    """
    checks: List[GdprCheck] = field(default_factory=list)
    # False when the detected region isn't subject to any GDPR-family
    # framework at all (see resolve_applicable_frameworks) — every check
    # above will then be present but reported as not-evaluated (None).
    applicable: bool = True
    # Display name of the specific GDPR-family framework in force for this
    # audit's region: "GDPR", "UK GDPR" or "Swiss FADP". None when not
    # applicable.
    framework_name: Optional[str] = "GDPR"

    def get(self, key: str) -> Optional[GdprCheck]:
        return next((c for c in self.checks if c.key == key), None)

    def as_dict(self) -> Dict[str, Optional[bool]]:
        return {c.key: c.passed for c in self.checks}

    @property
    def failed_checks(self) -> List[GdprCheck]:
        """Checks that ran and failed — derived from the live results, not
        from a fixed list. `passed is False` only: an unevaluated check
        (None) is "not tested", never a failure."""
        return [c for c in self.checks if c.passed is False]

    def as_evidence_dict(self) -> Dict[str, dict]:
        """
        One entry per check that *didn't pass*, so the report explains
        itself from what this audit actually observed rather than from
        fixed label text:

          failed (passed is False)      -> reason + any structured evidence
          not tested (passed is None)   -> reason only (why it couldn't be
                                           verified, e.g. runtime cookie
                                           timing unavailable)

        Each entry carries:
          reason   — the check's own `detail` string
          summary/items/items_label — structured evidence, when the check
                     has any (trackers_blocked_pre_consent,
                     cookies_blocked_pre_consent)

        Passed checks are left out, so this stays sparse. Stored in the
        existing gdpr_check_evidence JSON column — no schema change. Older
        audits lack `reason`; the report falls back to its fixed text.
        """
        out: Dict[str, dict] = {}
        for c in self.checks:
            if c.passed is True:
                continue
            entry = dict(c.evidence) if c.evidence else {}
            if c.detail:
                entry["reason"] = c.detail
            if entry:
                out[c.key] = entry
        return out

    @property
    def compliant(self) -> Optional[bool]:
        """
        True/False only when this GDPR-family framework actually applies
        to this audit's region and every required check ran; None when the
        region isn't subject to it at all (see `applicable`) — "unknown"
        must never collapse into "non-compliant". See
        `_REQUIRED_FOR_COMPLIANCE` for why the runtime-only
        reject_blocks_tracking check doesn't gate this verdict.
        """
        if not self.applicable:
            return None
        required = [c for c in self.checks if c.key in _REQUIRED_FOR_COMPLIANCE]
        return bool(required) and all(c.passed is True for c in required)

    @property
    def tested_count(self) -> int:
        return sum(1 for c in self.checks if c.passed is not None)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed is True)


def resolve_banner_detection(
    banner_detected: bool, runtime_result: Optional["ConsentRuntimeResult"]
) -> tuple:
    """
    Returns (banner_found, found_via_runtime_only).

    consent.banner.detect_banner reads only the raw fetched HTML, so a CMP
    that injects its banner with client-side JavaScript (OneTrust, Didomi,
    custom banners...) is invisible to it — the same blind spot that
    build_gdpr_assessment already works around for the Accept/Reject/
    Manage buttons. When the live Playwright pass ran and found a visible
    Accept or Reject control, a consent banner demonstrably exists, so
    that counts as detection too. Manage/Personalize alone isn't treated as
    proof (too generic a label to trust by itself), and a runtime pass that
    didn't run (`available` False) never upgrades a "not found".
    """
    runtime_saw_banner = bool(
        runtime_result and runtime_result.available and runtime_result.banner_detected
    )
    return (banner_detected or runtime_saw_banner), (runtime_saw_banner and not banner_detected)


_MAX_COOKIES_LISTED = 10


def _cookies_before_consent_check(
    runtime_result: Optional["ConsentRuntimeResult"],
) -> GdprCheck:
    """
    cookies_blocked_pre_consent, judged only from consent.runtime's
    before-consent snapshot: a fresh browser context, page loaded, *no*
    consent action taken yet, then every cookie in the jar recorded. That
    is a real timing measurement.

    The static Set-Cookie summary (consent.cookies) is deliberately NOT
    consulted here. It only sees cookies a server sets on the first HTTP
    response, so it misses everything client-side scripts set afterwards,
    and can't say anything about timing — using it here reported "no
    non-essential cookies" for pages that visibly had several.

    PASS / FAIL / None ("not tested") — and when the runtime pass didn't
    run or couldn't capture the snapshot, that's None, never a guessed
    FAIL or PASS. Cookie names, domains and categories all come from the
    snapshot itself; nothing here is site-specific.
    """
    key = "cookies_blocked_pre_consent"
    label = GDPR_CHECK_LABELS[key]

    before = runtime_result.before_consent if runtime_result else None
    if not (runtime_result and runtime_result.available and before and before.available):
        cause = (
            (before.error if before and before.error else None)
            or (runtime_result.error if runtime_result and runtime_result.error else None)
            or ("the live browser pass did not run" if not (runtime_result and runtime_result.available)
                else "the before-consent snapshot was not captured")
        )
        return GdprCheck(
            key, label, None,
            f"Not tested — runtime cookie timing could not be verified ({cause}).",
        )

    non_essential = before.non_essential_cookies
    if not non_essential:
        total = len(before.cookies)
        return GdprCheck(
            key, label, True,
            "No non-essential cookies were detected before consent"
            + (f" ({total} cookie(s) present, all essential)." if total else " (no cookies were present)."),
        )

    by_category: Dict[str, int] = {}
    for c in non_essential:
        name = "unclassified" if c.category == "unknown" else c.category
        by_category[name] = by_category.get(name, 0) + 1
    breakdown = ", ".join(f"{n} {cat}" for cat, n in sorted(by_category.items()))

    listed = [f"{c.name} ({c.domain}) — {'unclassified' if c.category == 'unknown' else c.category}"
              for c in non_essential[:_MAX_COOKIES_LISTED]]
    if len(non_essential) > _MAX_COOKIES_LISTED:
        listed.append(f"…and {len(non_essential) - _MAX_COOKIES_LISTED} more")

    return GdprCheck(
        key, label, False,
        f"{len(non_essential)} non-essential cookie(s) were present before any consent action.",
        evidence={
            "summary": f"By category: {breakdown}."
                       + (" Cookies not recognized as essential are treated as non-essential."
                          if "unclassified" in by_category else ""),
            "items": listed,
            "items_label": "Cookies present before consent",
        },
    )


def _consent_state_persistence_check(runtime_result: Optional["ConsentRuntimeResult"]) -> GdprCheck:
    """
    consent_state_persistence: after a visitor makes a choice, does the
    site remember it — a consent-state cookie gets set — rather than
    re-showing the banner on every single page load? Judged from
    consent.runtime's after-accept/after-reject cookie snapshots (the
    same live data cookies_blocked_pre_consent and reject_blocks_tracking
    use), checking whether any cookie set afterward matches a known
    CMP/consent-state naming pattern (see _CONSENT_STATE_COOKIE_RE).

    PASS / FAIL / None ("not tested") — a runtime pass that didn't run,
    or ran but never captured either post-choice snapshot, reports None,
    never a guessed FAIL.
    """
    key = "consent_state_persistence"
    label = GDPR_CHECK_LABELS[key]

    runtime_available = bool(runtime_result and runtime_result.available)
    accept_capture = runtime_result.after_accept if runtime_available else None
    reject_capture = runtime_result.after_reject if runtime_available else None
    capture_available = bool(
        (accept_capture and accept_capture.available) or (reject_capture and reject_capture.available)
    )

    if not capture_available:
        return GdprCheck(
            key, label, None,
            "Not tested — requires the optional live click-through (Playwright) pass to capture "
            "cookies set after a consent choice was made.",
        )

    cookies = []
    if accept_capture and accept_capture.available:
        cookies.extend(accept_capture.cookies)
    if reject_capture and reject_capture.available:
        cookies.extend(reject_capture.cookies)

    match = next((c for c in cookies if _CONSENT_STATE_COOKIE_RE.search(c.name)), None)
    if match:
        return GdprCheck(
            key, label, True,
            f"A consent-state cookie ({match.name}) was set after the visitor's choice, so the "
            "banner shouldn't reappear on the next page load.",
        )
    return GdprCheck(
        key, label, False,
        "No recognizable consent-state cookie was found after accepting/rejecting — the choice may "
        "not persist, and the banner could reappear on every visit.",
    )


def build_gdpr_assessment(
    *,
    page: ParsedPage,
    banner_detected: bool,
    buttons: ButtonsDetection,
    behavior: BehaviorResult,
    preferences: "PreferencesDetection",
    privacy_policy_url: Optional[str],
    cookie_summary: Optional[CookieSummary] = None,
    runtime_result: Optional["ConsentRuntimeResult"] = None,
    network_result: Optional["PreConsentNetworkResult"] = None,
    applicable: bool = True,
    framework_name: str = "GDPR",
) -> GdprAssessment:
    """
    Builds the twelve checks in `GDPR_CHECK_ORDER` from detections that
    consent/__init__.py's run_page_checks / analyze_site have already
    computed — no new page-scanning here except for `lawful_consent_controls`
    (pre-ticked non-essential checkboxes / implied-consent copy), which
    reads `page` directly since no other consent/* module currently
    detects it. Every other check just re-reads results other modules
    produced.

    `cookie_summary` is accepted for API compatibility but no longer feeds
    any check: Set-Cookie headers from one HTTP fetch can't establish
    what was set before consent (see _cookies_before_consent_check, which
    judges cookies_blocked_pre_consent from the runtime before-consent
    snapshot instead).

    `runtime_result` is optional for the same reason: reject_blocks_tracking
    needs consent.runtime's live click-through pass. None (no pass run,
    or the pass ran but never found/clicked a reject control) reports as
    "not evaluated", never as a silent pass or fail.

    `network_result` is optional too: consent.network's pre-consent
    capture (the same data check_pre_consent_network's findings and the
    old flat "N request(s) to known tracker(s) (...) were observed
    before any consent action" text are built from). When available and
    trackers_blocked_pre_consent fails, its actual captured requests
    back that check's `evidence` (count + tracker names) instead of
    leaving the UI with just the pass/fail bit.

    `applicable`/`framework_name` come from resolve_applicable_frameworks:
    when this audit's detected region isn't subject to any GDPR-family
    framework, none of the detections below are even run — every check is
    reported as not-evaluated (None) with a reason explaining why, rather
    than grading a framework that was never in legal scope for this site.
    GDPR / UK GDPR / Swiss FADP share the same checks; `framework_name`
    only changes the label shown for them.
    """
    if not applicable:
        checks = [
            GdprCheck(
                key, GDPR_CHECK_LABELS[key], None,
                f"Not assessed — {framework_name} does not apply to this audit's detected region.",
            )
            for key in GDPR_CHECK_ORDER
        ]
        return GdprAssessment(checks=checks, applicable=False, framework_name=None)

    checks: List[GdprCheck] = []

    banner_found, banner_via_runtime_only = resolve_banner_detection(banner_detected, runtime_result)
    checks.append(GdprCheck(
        "consent_banner", GDPR_CHECK_LABELS["consent_banner"], banner_found,
        ("A consent banner was found via live browser render — it isn't present in the raw HTML, "
         "so it's injected by client-side JavaScript (e.g. a CMP script)." if banner_via_runtime_only
         else "A consent banner/CMP was found on the page." if banner_found
         else "No consent banner or CMP was detected."),
    ))

    preticked = _detect_preticked_nonessential_checkboxes(page)
    implied_snippet = _detect_implied_consent_language(page.text_content)
    lawful_consent_ok = not preticked and not implied_snippet
    if lawful_consent_ok:
        lawful_consent_detail = (
            "No pre-ticked non-essential consent checkboxes or implied-consent "
            "(\"by continuing to browse...\") language were found."
        )
    else:
        reasons = []
        if preticked:
            reasons.append(
                f"{len(preticked)} non-essential checkbox(es) pre-checked by default "
                f"({'; '.join(preticked[:3])})"
            )
        if implied_snippet:
            reasons.append(f"implied-consent language found: \"{implied_snippet}\"")
        lawful_consent_detail = (
            "Consent isn't collected via a clear affirmative action — " + "; ".join(reasons)
            + " — both patterns GDPR's affirmative-action requirement (Art. 4(11)/Recital 32) "
              "and CNIL/ICO guidance rule out."
        )
    checks.append(GdprCheck(
        "lawful_consent_controls", GDPR_CHECK_LABELS["lawful_consent_controls"], lawful_consent_ok,
        lawful_consent_detail,
    ))

    # buttons.accept_found/reject_found/manage_found come from static HTML
    # only (consent.buttons.detect_buttons reads the raw fetched markup —
    # see that module's own docstring). Many CMPs (OneTrust, Didomi,
    # TrustArc, custom banners) inject the actual banner — and its
    # Accept/Reject/Personalize buttons — via client-side JavaScript after
    # the page loads, so those button labels simply never exist in the
    # HTML the plain HTTP fetch sees, even though a real visitor (and the
    # live Playwright runtime pass) sees them fine. Falling back to
    # runtime_result's rendered-DOM detection here — when the static
    # parse missed a control the live browser actually found — avoids
    # reporting "no accept/reject control" on a banner that plainly has
    # both, just because they're JS-rendered rather than static.
    runtime_available = bool(runtime_result and runtime_result.available)
    accept_found = buttons.accept_found or (runtime_available and runtime_result.accept_button_found)
    reject_found = buttons.reject_found or (runtime_available and runtime_result.reject_button_found)
    manage_found = buttons.manage_found or (runtime_available and runtime_result.manage_button_found)

    accept_via_runtime_only = accept_found and not buttons.accept_found
    reject_via_runtime_only = reject_found and not buttons.reject_found
    manage_via_runtime_only = manage_found and not buttons.manage_found

    checks.append(GdprCheck(
        "accept_control", GDPR_CHECK_LABELS["accept_control"], accept_found,
        (f"Accept control found: {', '.join(buttons.accept_labels[:3])}." if buttons.accept_found
         else "Accept control found via live browser render — its label isn't present in the raw "
              "HTML, so it's rendered by client-side JavaScript (e.g. a CMP script) rather than "
              "server-rendered markup." if accept_via_runtime_only
         else "No recognizable accept control was found."),
    ))

    checks.append(GdprCheck(
        "reject_control", GDPR_CHECK_LABELS["reject_control"], reject_found,
        (f"Reject control found: {', '.join(buttons.reject_labels[:3])}." if buttons.reject_found
         else "Reject control found via live browser render — its label isn't present in the raw "
              "HTML, so it's rendered by client-side JavaScript (e.g. a CMP script) rather than "
              "server-rendered markup." if reject_via_runtime_only
         else "No recognizable reject control was found."),
    ))

    has_reject_parity = accept_found and reject_found
    checks.append(GdprCheck(
        "reject_parity", GDPR_CHECK_LABELS["reject_parity"], has_reject_parity,
        "Reject is offered with the same one-click access as Accept." if has_reject_parity
        else "Accept and reject aren't offered on equal footing (accept-only, or reject buried/absent) — "
             "a pattern CNIL/ICO have flagged as a dark pattern.",
    ))

    trackers_evidence = None
    if not behavior.blocks_scripts_pre_consent and network_result is not None and network_result.available:
        tracker_requests = network_result.tracker_requests
        if tracker_requests:
            names = sorted({r.tracker_name for r in tracker_requests})
            trackers_evidence = {
                "summary": f"{len(tracker_requests)} tracker request(s) detected before consent.",
                "items": names,
                "items_label": "Detected trackers",
            }
    checks.append(GdprCheck(
        "trackers_blocked_pre_consent", GDPR_CHECK_LABELS["trackers_blocked_pre_consent"],
        behavior.blocks_scripts_pre_consent,
        ("Confirmed via live network capture: " if behavior.verified
         else "Based on the page's declared Consent Mode default only, not independently verified: ")
        + ("non-essential scripts are held back until consent." if behavior.blocks_scripts_pre_consent
           else "non-essential scripts are not held back until consent."),
        evidence=trackers_evidence,
    ))

    checks.append(_cookies_before_consent_check(runtime_result))

    checks.append(GdprCheck(
        "consent_is_granular", GDPR_CHECK_LABELS["consent_is_granular"], manage_found,
        (f"A 'Manage Preferences'-style control is offered alongside Accept/Reject, letting "
         f"visitors opt into categories individually: {', '.join(buttons.manage_labels[:3])}."
         if buttons.manage_found
         else "A 'Manage Preferences'-style control was found via live browser render, not in "
              "the raw HTML — it's rendered by client-side JavaScript." if manage_via_runtime_only
         else "No manage/customize option was found in the banner — only an all-or-nothing choice."),
    ))

    withdrawal_ok = preferences.link_found or preferences.trigger_found
    checks.append(GdprCheck(
        "consent_withdrawal_available", GDPR_CHECK_LABELS["consent_withdrawal_available"], withdrawal_ok,
        "A persistent link or CMP trigger to revisit cookie preferences was found." if withdrawal_ok
        else "No persistent footer/nav link or CMP trigger was found for withdrawing consent later.",
    ))

    privacy_ok = privacy_policy_url is not None
    checks.append(GdprCheck(
        "privacy_policy_available", GDPR_CHECK_LABELS["privacy_policy_available"], privacy_ok,
        f"Privacy policy link found ({privacy_policy_url})." if privacy_ok
        else "No privacy policy or notice link was found.",
    ))

    checks.append(_consent_state_persistence_check(runtime_result))

    if runtime_result is None or runtime_result.reject_blocks_tracking is None:
        reject_runtime_check = GdprCheck(
            "reject_blocks_tracking", GDPR_CHECK_LABELS["reject_blocks_tracking"], None,
            "Not evaluated — requires the optional live click-through (Playwright) pass, which "
            "either didn't run or couldn't locate/click a reject control.",
        )
    else:
        ok = runtime_result.reject_blocks_tracking
        reject_runtime_check = GdprCheck(
            "reject_blocks_tracking", GDPR_CHECK_LABELS["reject_blocks_tracking"], ok,
            "Clicking Reject actually stopped tracker requests and further non-essential cookies." if ok
            else "Clicking Reject did not stop tracker requests/non-essential cookies — the control "
                 "doesn't do what it claims.",
        )
    checks.append(reject_runtime_check)

    return GdprAssessment(checks=checks, applicable=True, framework_name=framework_name)


# The seven individual technical checks that make up a CCPA/CPRA
# assessment, in display order — the CCPA counterpart to
# GDPR_CHECK_ORDER above. CCPA compliance was previously a single
# `ccpa_link_found and privacy_policy_url is not None` boolean; that
# collapsed "no Do Not Sell link" and "no opt-out mechanism at all"
# into the same undifferentiated False, the same problem
# GDPR_CHECK_ORDER already fixed for GDPR.
CCPA_CHECK_ORDER = (
    "privacy_policy_available",
    "do_not_sell_link",
    "opt_out_mechanism",
    "privacy_choices_link",
    "gpc_honored",
    "opt_out_behavior_verified",
    "advertising_analytics_behavior",
)

CCPA_CHECK_LABELS: Dict[str, str] = {
    "privacy_policy_available": "Privacy policy available",
    "do_not_sell_link": '"Do Not Sell or Share My Information" link present',
    "opt_out_mechanism": "Opt-out mechanism reachable",
    "privacy_choices_link": '"Your Privacy Choices" link present',
    "gpc_honored": "Global Privacy Control (GPC) signal handling detected",
    "opt_out_behavior_verified": "Opt-out actually stops tracking",
    "advertising_analytics_behavior": "Advertising/analytics behavior after opt-out (where applicable)",
}

# "opt_out_behavior_verified" and "advertising_analytics_behavior" are
# excluded for the same reason GDPR's "reject_blocks_tracking" is: both
# depend on the optional Playwright runtime pass, so they're routinely
# None ("not tested") on a static-only audit.
_CCPA_REQUIRED_FOR_COMPLIANCE = frozenset(CCPA_CHECK_ORDER) - {
    "opt_out_behavior_verified", "advertising_analytics_behavior",
}

CCPA_PROFILE = RegionalScoringProfile(
    name="CCPA/CPRA",
    check_order=CCPA_CHECK_ORDER,
    check_labels=CCPA_CHECK_LABELS,
    runtime_only_checks=frozenset({"opt_out_behavior_verified", "advertising_analytics_behavior"}),
)

# Both regional profiles, keyed the same way resolve_applicable_frameworks'
# ApplicableFrameworks.assess_gdpr / assess_ccpa flags name them, so a
# caller (e.g. a report) can go straight from "which framework applies"
# to "what does that framework check" without importing four separate
# module constants.
REGIONAL_SCORING_PROFILES: Dict[str, RegionalScoringProfile] = {
    "GDPR": GDPR_PROFILE,
    "CCPA": CCPA_PROFILE,
}


@dataclass
class CcpaCheck:
    key: str
    label: str
    passed: Optional[bool]  # None = not evaluated
    detail: str = ""


@dataclass
class CcpaAssessment:
    """CCPA counterpart to GdprAssessment — see that class's docstring
    for why a single `ccpa_compliant` boolean isn't enough on its own."""
    checks: List[CcpaCheck] = field(default_factory=list)
    # False when the detected region isn't subject to CCPA/CPRA at all
    # (see resolve_applicable_frameworks) — every check above will then be
    # present but reported as not-evaluated (None).
    applicable: bool = True

    def get(self, key: str) -> Optional[CcpaCheck]:
        return next((c for c in self.checks if c.key == key), None)

    def as_dict(self) -> Dict[str, Optional[bool]]:
        return {c.key: c.passed for c in self.checks}

    @property
    def compliant(self) -> Optional[bool]:
        """
        True/False only when CCPA/CPRA actually applies to this audit's
        region and every required check ran; None when it doesn't apply at
        all — "unknown"/"not applicable" must never collapse into
        "non-compliant".
        """
        if not self.applicable:
            return None
        required = [c for c in self.checks if c.key in _CCPA_REQUIRED_FOR_COMPLIANCE]
        return bool(required) and all(c.passed is True for c in required)

    @property
    def tested_count(self) -> int:
        return sum(1 for c in self.checks if c.passed is not None)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed is True)


def build_ccpa_assessment(
    *,
    privacy_policy_url: Optional[str],
    ccpa_link_found: bool,
    privacy_choices: CcpaLinkDetection,
    preferences: "PreferencesDetection",
    gpc_honored: bool,
    runtime_result: Optional["ConsentRuntimeResult"] = None,
    applicable: bool = True,
) -> CcpaAssessment:
    """
    Builds the seven checks in `CCPA_CHECK_ORDER`, fetched/detected the
    same way build_gdpr_assessment builds GDPR's twelve: every check here
    is either read from a detection another consent/* module already ran
    (consent.consent_score.detect_privacy_policy / detect_ccpa_link,
    consent.ccpa.detect_privacy_choices_link / detect_gpc_handling,
    consent.preferences.detect_preferences_link) or, for
    opt_out_behavior_verified and advertising_analytics_behavior, the
    optional live click-through (consent.runtime) pass — no new
    page-scanning happens here.

    `applicable` comes from resolve_applicable_frameworks: when this
    audit's detected region isn't California (and isn't Other-US with
    California applicability configured/detected), none of the detections
    below are run — every check is reported as not-evaluated (None) with a
    reason, rather than grading a framework that was never in scope.
    """
    if not applicable:
        checks = [
            CcpaCheck(
                key, CCPA_CHECK_LABELS[key], None,
                "Not assessed — CCPA/CPRA does not apply to this audit's detected region.",
            )
            for key in CCPA_CHECK_ORDER
        ]
        return CcpaAssessment(checks=checks, applicable=False)

    checks: List[CcpaCheck] = []

    privacy_ok = privacy_policy_url is not None
    checks.append(CcpaCheck(
        "privacy_policy_available", CCPA_CHECK_LABELS["privacy_policy_available"], privacy_ok,
        f"Privacy policy link found ({privacy_policy_url})." if privacy_ok
        else "No privacy policy or notice link was found.",
    ))

    checks.append(CcpaCheck(
        "do_not_sell_link", CCPA_CHECK_LABELS["do_not_sell_link"], ccpa_link_found,
        "A \"Do Not Sell or Share My Personal Information\" link was found." if ccpa_link_found
        else "No \"Do Not Sell or Share My Personal Information\" link was found.",
    ))

    opt_out_ok = preferences.link_found or preferences.trigger_found or ccpa_link_found or privacy_choices.found
    checks.append(CcpaCheck(
        "opt_out_mechanism", CCPA_CHECK_LABELS["opt_out_mechanism"], opt_out_ok,
        "A persistent opt-out link or CMP trigger is reachable." if opt_out_ok
        else "No persistent, reachable opt-out mechanism (link or CMP trigger) was found.",
    ))

    checks.append(CcpaCheck(
        "privacy_choices_link", CCPA_CHECK_LABELS["privacy_choices_link"], privacy_choices.found,
        f"Found a privacy-choices/CCPA link: \"{privacy_choices.text}\"." if privacy_choices.found
        else "No \"Your Privacy Choices\" / California privacy rights link was found.",
    ))

    checks.append(CcpaCheck(
        "gpc_honored", CCPA_CHECK_LABELS["gpc_honored"], gpc_honored,
        "The page's own scripts read navigator.globalPrivacyControl." if gpc_honored
        else "No reference to navigator.globalPrivacyControl was found in the page's scripts — "
             "the Global Privacy Control opt-out signal doesn't appear to be honored automatically.",
    ))

    if runtime_result is None or runtime_result.reject_blocks_tracking is None:
        opt_out_behavior_check = CcpaCheck(
            "opt_out_behavior_verified", CCPA_CHECK_LABELS["opt_out_behavior_verified"], None,
            "Not evaluated — requires the optional live click-through (Playwright) pass, which "
            "either didn't run or couldn't locate/click an opt-out control.",
        )
    else:
        ok = runtime_result.reject_blocks_tracking
        opt_out_behavior_check = CcpaCheck(
            "opt_out_behavior_verified", CCPA_CHECK_LABELS["opt_out_behavior_verified"], ok,
            "Clicking the opt-out control actually stopped tracker requests and further "
            "non-essential cookies." if ok
            else "Clicking the opt-out control did not stop tracker requests/non-essential "
                 "cookies — the same live pass used for GDPR's reject check found tracking "
                 "still active afterward.",
        )
    checks.append(opt_out_behavior_check)

    checks.append(_advertising_analytics_behavior_check(runtime_result))

    return CcpaAssessment(checks=checks, applicable=True)


def _advertising_analytics_behavior_check(
    runtime_result: Optional["ConsentRuntimeResult"],
) -> CcpaCheck:
    """
    advertising_analytics_behavior: CCPA/CPRA's opt-out right is
    specifically about the sale/sharing of personal information for
    cross-context behavioral advertising — narrower than GDPR's general
    reject_blocks_tracking, this singles out whether *named*
    advertising/analytics trackers (consent.network.KNOWN_TRACKER_DOMAINS
    — Google Ads, Meta Pixel, TikTok Pixel, etc.) are still firing after
    the visitor opts out, since that's the concrete, checkable signal
    that a "sale"/"share" is still happening post opt-out. Read from the
    same after_reject snapshot consent.runtime's reject leg already
    captures — the opt-out click and GDPR's reject click are the same
    live pass, just interpreted for a different legal question.

    "(where applicable)" in the check's own label reflects that a site
    with no advertising/analytics trackers at all simply has nothing to
    opt out of — that's still a pass (0 trackers observed), not
    "untested" or "failed".
    """
    key = "advertising_analytics_behavior"
    label = CCPA_CHECK_LABELS[key]

    after_reject = runtime_result.after_reject if runtime_result and runtime_result.available else None
    if not (after_reject and after_reject.available):
        return CcpaCheck(
            key, label, None,
            "Not evaluated — requires the optional live click-through (Playwright) pass, which "
            "either didn't run or couldn't locate/click an opt-out control.",
        )

    tracker_requests = after_reject.tracker_requests
    if not tracker_requests:
        return CcpaCheck(
            key, label, True,
            "No advertising/analytics tracker requests were observed after opting out.",
        )

    names = sorted({r.tracker_name for r in tracker_requests})
    return CcpaCheck(
        key, label, False,
        f"{len(tracker_requests)} advertising/analytics request(s) to known tracker(s) "
        f"({', '.join(names)}) were still observed after opting out.",
    )


@dataclass
class ConsentSummary:
    """Field-for-field match with models.consent.Consent, minus audit_id/id/created_at."""
    has_cookie_banner: bool = False
    banner_blocks_scripts_pre_consent: bool = False

    # Region this audit was evaluated against, and which single regional
    # framework (if any) that resolved to — see resolve_applicable_frameworks.
    # Field names below match models.consent.Consent's columns 1:1 so
    # `Consent(audit_id=..., **vars(summary))` keeps working without a
    # translation step. detected_region is the REGION_* bucket
    # (REGION_UNKNOWN when no region was passed in / detected);
    # detected_country/region_confidence/region_detection_source/
    # region_detection_reason default to their "no signal found" values
    # and are only meaningfully populated when build_consent_summary is
    # given a consent.region_detector.RegionDetectionResult (see
    # `region_detection` param below) rather than a bare region string.
    detected_region: str = REGION_UNKNOWN
    detected_country: Optional[str] = None
    # At most one framework ever applies per audit (resolve_applicable_
    # frameworks picks a single regional framework), so one field covers
    # both the GDPR-family and CCPA cases — "GDPR" / "UK GDPR" /
    # "Swiss FADP" / "CCPA/CPRA" / None.
    compliance_framework: Optional[str] = None
    region_confidence: str = "none"          # "high" | "medium" | "low" | "none"
    region_detection_source: str = "None"    # e.g. "Domain + hreflang"
    region_detection_reason: str = ""

    # None ("not assessed") whenever this audit's region isn't subject to
    # the relevant framework at all — NEVER coerced to False, since that
    # would misreport "unknown"/"not applicable" as "non-compliant".
    # NOTE: models.consent.Consent currently declares gdpr_compliant/
    # ccpa_compliant as non-nullable Boolean columns; that column needs a
    # migration to nullable (or an explicit "not applicable" sentinel)
    # before this can be persisted as-is — see gdpr_assessed/ccpa_assessed
    # below for a non-nullable-friendly alternative in the meantime.
    gdpr_compliant: Optional[bool] = None
    # Whether GDPR/UK GDPR/Swiss FADP applied to this audit at all (i.e.
    # GdprAssessment.applicable) — check this before reading gdpr_compliant
    # as a real verdict; a non-nullable DB column can safely store
    # `gdpr_compliant or False` alongside this flag without losing the
    # "not assessed" signal.
    gdpr_assessed: bool = False
    # Per-check breakdown behind gdpr_compliant above — key -> True/False/None
    # ("not evaluated"), in GDPR_CHECK_ORDER. gdpr_compliant is just
    # GdprAssessment.compliant computed from these; the dict is what a
    # report should actually render instead of the single bit.
    gdpr_checks: Dict[str, Optional[bool]] = field(default_factory=dict)
    # Structured evidence for whichever gdpr_checks entries have it (see
    # GdprCheck.evidence) — sparse, keyed the same as gdpr_checks, only
    # present for checks with real underlying data to show (currently
    # just trackers_blocked_pre_consent).
    gdpr_check_evidence: Dict[str, dict] = field(default_factory=dict)

    ccpa_compliant: Optional[bool] = None
    # Whether CCPA/CPRA applied to this audit at all (i.e.
    # CcpaAssessment.applicable) — same purpose as gdpr_assessed above.
    ccpa_assessed: bool = False
    # Per-check breakdown behind ccpa_compliant above — key -> True/False/None
    # ("not evaluated"), in CCPA_CHECK_ORDER. ccpa_compliant is just
    # CcpaAssessment.compliant computed from these; the dict is what a
    # report should actually render instead of the single bit (same
    # relationship gdpr_checks has to gdpr_compliant above).
    ccpa_checks: Dict[str, Optional[bool]] = field(default_factory=dict)
    privacy_policy_found: bool = False
    privacy_policy_url: Optional[str] = None
    cookies_detected: List[dict] = field(default_factory=list)
    third_party_trackers: List[str] = field(default_factory=list)
    consent_score: int = 0

    # Set by consent.analyze_site after screenshot capture / the runtime
    # pass complete — build_consent_summary leaves these at their default
    # since analyze_site computes the screenshots after building the
    # summary object (see consent/__init__.py). Left as real fields here
    # (rather than a separate kwarg on the Consent(...) call) so the whole
    # row can persist from a single `Consent(audit_id=..., **vars(summary))`.
    banner_screenshot_path: Optional[str] = None
    preferences_screenshot_path: Optional[str] = None
    reject_screenshot_path: Optional[str] = None
    accept_screenshot_path: Optional[str] = None

    # consent.runtime.run_consent_runtime's click-through verdicts.
    # runtime_available: the Playwright pass executed at all (browser
    # launched, page loaded) — independent of whether it found anything to
    # click. runtime_tested: it additionally succeeded in clicking Accept
    # and/or Reject, i.e. reject_blocks_tracking/accept_allows_tracking/
    # personalize_exposes_controls below are real verdicts, not just "not
    # tested". runtime_result is the full ConsentRuntimeResult, serialized,
    # kept for the evidence-package export and the report's screenshot strip.
    runtime_available: bool = False
    runtime_tested: bool = False
    runtime_result: Optional[dict] = None


def detect_privacy_policy(page: ParsedPage) -> Optional[str]:
    """Returns the absolute-or-relative href of a privacy policy link, if any is found."""
    for tag in page.anchor_tags:
        text = tag.get_text(strip=True) or ""
        href = tag.get("href") or ""
        if _PRIVACY_POLICY_LINK_RE.search(text) or _PRIVACY_POLICY_HREF_RE.search(href):
            return href or None
    return None


def detect_ccpa_link(page: ParsedPage) -> bool:
    for tag in page.anchor_tags:
        if _CCPA_LINK_RE.search(tag.get_text(strip=True) or ""):
            return True
    return False


def build_consent_summary(
    *,
    page: ParsedPage,
    banner_detected: bool,
    buttons: ButtonsDetection,
    behavior: BehaviorResult,
    consent_mode: ConsentModeDetection,
    cookie_summary: CookieSummary,
    preferences: PreferencesDetection,
    score_result: ConsentScoreResult,
    runtime_result: Optional["ConsentRuntimeResult"] = None,
    network_result: Optional["PreConsentNetworkResult"] = None,
    region: Optional[str] = None,
    california_applicability: Optional[bool] = None,
    region_detection: Optional["RegionDetectionResult"] = None,
) -> ConsentSummary:
    """
    Assembles a ConsentSummary ready to pass straight into
    models.consent.Consent(**vars(summary), audit_id=...). Takes the
    individual detect_*()/evaluate_*() results rather than re-deriving
    them, since consent.analyze_page already computed all of them once.

    GDPR compliance is now judged as ten separate checks (see
    build_gdpr_assessment / GDPR_CHECK_ORDER) rather than one hand-rolled
    boolean — this function just calls that and folds the roll-up verdict
    plus the full per-check breakdown into the summary. CCPA compliance is
    judged the same way, as six separate checks (see build_ccpa_assessment
    / CCPA_CHECK_ORDER) covering its own required disclosures — a "Do Not
    Sell/Share" link, a "Your Privacy Choices" link, a reachable opt-out
    mechanism, and Global Privacy Control signal handling — rather than
    GDPR's stricter opt-in banner, which isn't a CCPA requirement, so the
    two verdicts are allowed to disagree.

    `region`/`california_applicability` are resolved once via
    resolve_applicable_frameworks into which single framework this audit
    is actually judged against (EU/EEA/UK/Switzerland -> the matching
    GDPR-family framework only; California -> CCPA only; unrecognized US
    only if california_applicability says so; anything else/unknown ->
    neither). Whichever framework doesn't apply is never evaluated at all,
    and its compliant flag comes back None ("not assessed"), not False.
    `region` defaults to None (treated as unknown, so neither framework is
    assessed) until the caller wires in real region detection.

    `region_detection` is the richer alternative to passing a bare
    `region` string: consent.region_detector.detect_region's full result
    (region bucket + country label + confidence + which signal(s) won +
    a human-readable reason). When given, its `.region` is what actually
    drives resolve_applicable_frameworks (the plain `region` param is
    ignored in favor of it), and its country/confidence/source/reason
    are copied straight onto the summary's detected_country/
    region_confidence/region_detection_source/region_detection_reason
    fields — the detail models.consent.Consent's history-page columns
    exist to show. Its own `.framework` is intentionally NOT trusted
    directly for compliance_framework below; that's still derived from
    resolve_applicable_frameworks (this module's own source of truth for
    the region -> framework mapping, including california_applicability)
    so the two never disagree even though region_detector computes the
    same mapping once internally for its own display purposes. Omit
    `region_detection` (pass a bare `region` string, or nothing) and the
    detection-detail fields stay at their "no signal" defaults.

    `preferences` should be consent.preferences.detect_preferences_link's
    result for this page — needed here (not just the pre-reduced
    `preferences_found` bool) so consent_withdrawal_available can report
    its own detail text.
    """
    privacy_policy_url = detect_privacy_policy(page)
    ccpa_link_found = detect_ccpa_link(page)
    privacy_choices = detect_privacy_choices_link(page)
    gpc_honored = detect_gpc_handling(page)

    effective_region = region_detection.region if region_detection is not None else region
    frameworks = resolve_applicable_frameworks(effective_region, california_applicability=california_applicability)
    compliance_framework = frameworks.gdpr_framework_name or ("CCPA/CPRA" if frameworks.assess_ccpa else None)

    gdpr_assessment = build_gdpr_assessment(
        page=page,
        banner_detected=banner_detected,
        buttons=buttons,
        behavior=behavior,
        preferences=preferences,
        privacy_policy_url=privacy_policy_url,
        cookie_summary=cookie_summary,
        runtime_result=runtime_result,
        network_result=network_result,
        applicable=frameworks.assess_gdpr,
        framework_name=frameworks.gdpr_framework_name or "GDPR",
    )
    gdpr_compliant = gdpr_assessment.compliant

    ccpa_assessment = build_ccpa_assessment(
        privacy_policy_url=privacy_policy_url,
        ccpa_link_found=ccpa_link_found,
        privacy_choices=privacy_choices,
        preferences=preferences,
        gpc_honored=gpc_honored,
        runtime_result=runtime_result,
        applicable=frameworks.assess_ccpa,
    )
    ccpa_compliant = ccpa_assessment.compliant

    runtime_available = bool(runtime_result and runtime_result.available)
    # "Tested" means the engine actually got as far as clicking a button —
    # an available-but-empty pass (e.g. no banner to click) should still
    # show as "not tested" to the report, not as a silent pass/fail.
    runtime_tested = bool(
        runtime_result and runtime_result.available
        and (runtime_result.accept_clicked or runtime_result.reject_clicked)
    )

    banner_found, _ = resolve_banner_detection(banner_detected, runtime_result)

    return ConsentSummary(
        has_cookie_banner=banner_found,
        banner_blocks_scripts_pre_consent=behavior.blocks_scripts_pre_consent,
        detected_region=frameworks.region,
        detected_country=region_detection.region_label if region_detection is not None else None,
        compliance_framework=compliance_framework,
        region_confidence=region_detection.confidence if region_detection is not None else "none",
        region_detection_source=region_detection.source if region_detection is not None else "None",
        region_detection_reason=region_detection.reason if region_detection is not None else "",
        gdpr_compliant=gdpr_compliant,
        gdpr_assessed=gdpr_assessment.applicable,
        gdpr_checks=gdpr_assessment.as_dict(),
        gdpr_check_evidence=gdpr_assessment.as_evidence_dict(),
        ccpa_compliant=ccpa_compliant,
        ccpa_assessed=ccpa_assessment.applicable,
        ccpa_checks=ccpa_assessment.as_dict(),
        privacy_policy_found=privacy_policy_url is not None,
        privacy_policy_url=privacy_policy_url,
        cookies_detected=cookie_summary.cookies_detected,
        third_party_trackers=cookie_summary.third_party_trackers,
        consent_score=score_result.overall,
        runtime_available=runtime_available,
        runtime_tested=runtime_tested,
        runtime_result=dataclasses.asdict(runtime_result) if runtime_result else None,
    )
