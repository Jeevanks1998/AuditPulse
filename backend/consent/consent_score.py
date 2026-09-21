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

if TYPE_CHECKING:  # avoid importing consent.runtime at module load time
    from consent.runtime import ConsentRuntimeResult
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


# The ten individual technical checks that make up a GDPR assessment,
# in display order. Each maps to one specific, independently-testable
# requirement rather than being folded into a single pass/fail bit —
# see GdprAssessment below for why that distinction matters.
GDPR_CHECK_ORDER = (
    "consent_banner",
    "accept_control",
    "reject_control",
    "reject_parity",
    "trackers_blocked_pre_consent",
    "cookies_blocked_pre_consent",
    "consent_is_granular",
    "privacy_policy_available",
    "consent_withdrawal_available",
    "reject_blocks_tracking",
)

GDPR_CHECK_LABELS: Dict[str, str] = {
    "consent_banner": "Consent banner",
    "accept_control": "Accept control",
    "reject_control": "Reject control",
    "reject_parity": "Reject parity",
    "trackers_blocked_pre_consent": "Non-essential trackers blocked before consent",
    "cookies_blocked_pre_consent": "Non-essential cookies blocked before consent",
    "consent_is_granular": "Consent is granular",
    "privacy_policy_available": "Privacy policy available",
    "consent_withdrawal_available": "Consent withdrawal available",
    "reject_blocks_tracking": "Reject actually blocks tracking",
}

# "reject_blocks_tracking" is deliberately excluded: it's the only check
# here that depends on the optional Playwright runtime pass, so it's
# routinely None ("not tested") on a static-only audit — counting an
# untested check as a failure would make every such audit non-compliant
# regardless of what the banner itself actually does.
_REQUIRED_FOR_COMPLIANCE = frozenset(GDPR_CHECK_ORDER) - {"reject_blocks_tracking"}


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
    def compliant(self) -> bool:
        """
        True only when every required check ran and passed. See
        `_REQUIRED_FOR_COMPLIANCE` for why the runtime-only
        reject_blocks_tracking check doesn't gate this verdict.
        """
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


def build_gdpr_assessment(
    *,
    banner_detected: bool,
    buttons: ButtonsDetection,
    behavior: BehaviorResult,
    preferences: "PreferencesDetection",
    privacy_policy_url: Optional[str],
    cookie_summary: Optional[CookieSummary] = None,
    runtime_result: Optional["ConsentRuntimeResult"] = None,
    network_result: Optional["PreConsentNetworkResult"] = None,
) -> GdprAssessment:
    """
    Builds the ten checks in `GDPR_CHECK_ORDER` from detections that
    consent/__init__.py's run_page_checks / analyze_site have already
    computed — no new page-scanning here, this only re-reads results
    other modules produced.

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
    """
    checks: List[GdprCheck] = []

    banner_found, banner_via_runtime_only = resolve_banner_detection(banner_detected, runtime_result)
    checks.append(GdprCheck(
        "consent_banner", GDPR_CHECK_LABELS["consent_banner"], banner_found,
        ("A consent banner was found via live browser render — it isn't present in the raw HTML, "
         "so it's injected by client-side JavaScript (e.g. a CMP script)." if banner_via_runtime_only
         else "A consent banner/CMP was found on the page." if banner_found
         else "No consent banner or CMP was detected."),
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

    privacy_ok = privacy_policy_url is not None
    checks.append(GdprCheck(
        "privacy_policy_available", GDPR_CHECK_LABELS["privacy_policy_available"], privacy_ok,
        f"Privacy policy link found ({privacy_policy_url})." if privacy_ok
        else "No privacy policy or notice link was found.",
    ))

    withdrawal_ok = preferences.link_found or preferences.trigger_found
    checks.append(GdprCheck(
        "consent_withdrawal_available", GDPR_CHECK_LABELS["consent_withdrawal_available"], withdrawal_ok,
        "A persistent link or CMP trigger to revisit cookie preferences was found." if withdrawal_ok
        else "No persistent footer/nav link or CMP trigger was found for withdrawing consent later.",
    ))

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

    return GdprAssessment(checks=checks)


# The six individual technical checks that make up a CCPA/CPRA
# assessment, in display order — the CCPA counterpart to
# GDPR_CHECK_ORDER above. CCPA compliance was previously a single
# `ccpa_link_found and privacy_policy_url is not None` boolean; that
# collapsed "no Do Not Sell link" and "no opt-out mechanism at all"
# into the same undifferentiated False, the same problem
# GDPR_CHECK_ORDER already fixed for GDPR.
CCPA_CHECK_ORDER = (
    "privacy_policy_available",
    "privacy_choices_link",
    "do_not_sell_link",
    "opt_out_mechanism",
    "gpc_honored",
    "opt_out_behavior_verified",
)

CCPA_CHECK_LABELS: Dict[str, str] = {
    "privacy_policy_available": "Privacy policy available",
    "privacy_choices_link": '"Your Privacy Choices" link present',
    "do_not_sell_link": '"Do Not Sell or Share My Information" link present',
    "opt_out_mechanism": "Opt-out mechanism reachable",
    "gpc_honored": "Global Privacy Control (GPC) signal handling detected",
    "opt_out_behavior_verified": "Opt-out actually stops tracking",
}

# "opt_out_behavior_verified" is excluded for the same reason
# GDPR's "reject_blocks_tracking" is: it depends on the optional
# Playwright runtime pass, so it's routinely None ("not tested") on a
# static-only audit.
_CCPA_REQUIRED_FOR_COMPLIANCE = frozenset(CCPA_CHECK_ORDER) - {"opt_out_behavior_verified"}


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

    def get(self, key: str) -> Optional[CcpaCheck]:
        return next((c for c in self.checks if c.key == key), None)

    def as_dict(self) -> Dict[str, Optional[bool]]:
        return {c.key: c.passed for c in self.checks}

    @property
    def compliant(self) -> bool:
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
) -> CcpaAssessment:
    """
    Builds the six checks in `CCPA_CHECK_ORDER`, fetched/detected the
    same way build_gdpr_assessment builds GDPR's ten: every check here
    is either read from a detection another consent/* module already
    ran (consent.consent_score.detect_privacy_policy /
    detect_ccpa_link, consent.ccpa.detect_privacy_choices_link /
    detect_gpc_handling, consent.preferences.detect_preferences_link)
    or, for opt_out_behavior_verified, the optional live click-through
    (consent.runtime) pass — no new page-scanning happens here.
    """
    checks: List[CcpaCheck] = []

    privacy_ok = privacy_policy_url is not None
    checks.append(CcpaCheck(
        "privacy_policy_available", CCPA_CHECK_LABELS["privacy_policy_available"], privacy_ok,
        f"Privacy policy link found ({privacy_policy_url})." if privacy_ok
        else "No privacy policy or notice link was found.",
    ))

    checks.append(CcpaCheck(
        "privacy_choices_link", CCPA_CHECK_LABELS["privacy_choices_link"], privacy_choices.found,
        f"Found a privacy-choices/CCPA link: \"{privacy_choices.text}\"." if privacy_choices.found
        else "No \"Your Privacy Choices\" / California privacy rights link was found.",
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

    return CcpaAssessment(checks=checks)


@dataclass
class ConsentSummary:
    """Field-for-field match with models.consent.Consent, minus audit_id/id/created_at."""
    has_cookie_banner: bool = False
    banner_blocks_scripts_pre_consent: bool = False
    gdpr_compliant: bool = False
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
    ccpa_compliant: bool = False
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

    `preferences` should be consent.preferences.detect_preferences_link's
    result for this page — needed here (not just the pre-reduced
    `preferences_found` bool) so consent_withdrawal_available can report
    its own detail text.
    """
    privacy_policy_url = detect_privacy_policy(page)
    ccpa_link_found = detect_ccpa_link(page)
    privacy_choices = detect_privacy_choices_link(page)
    gpc_honored = detect_gpc_handling(page)

    gdpr_assessment = build_gdpr_assessment(
        banner_detected=banner_detected,
        buttons=buttons,
        behavior=behavior,
        preferences=preferences,
        privacy_policy_url=privacy_policy_url,
        cookie_summary=cookie_summary,
        runtime_result=runtime_result,
        network_result=network_result,
    )
    gdpr_compliant = gdpr_assessment.compliant

    ccpa_assessment = build_ccpa_assessment(
        privacy_policy_url=privacy_policy_url,
        ccpa_link_found=ccpa_link_found,
        privacy_choices=privacy_choices,
        preferences=preferences,
        gpc_honored=gpc_honored,
        runtime_result=runtime_result,
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
        gdpr_compliant=gdpr_compliant,
        gdpr_checks=gdpr_assessment.as_dict(),
        gdpr_check_evidence=gdpr_assessment.as_evidence_dict(),
        ccpa_compliant=ccpa_compliant,
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
