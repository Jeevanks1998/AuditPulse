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

from consent.region import (
    FW_CCPA,
    FW_DPDP,
    FW_GDPR,
    RegionResult,
    detect_region,
)
from consent.behavior import BehaviorResult
from consent.buttons import ACTION_LABELS, ButtonsDetection
from consent.ccpa import CcpaLinkDetection, CcpaSignals, detect_ccpa_signals, detect_do_not_sell_link
from consent.consent_mode import ConsentModeDetection
from consent.cookies import bucket_cookies
from consent.preferences import PreferencesDetection
from cookies.storage import CookieSummary

if TYPE_CHECKING:  # avoid importing consent.runtime at module load time
    from consent.runtime import ConsentRuntimeResult
    from consent.network import PreConsentNetworkResult

MODULE = "consent"

SEVERITY_PENALTY = {"critical": 30, "warning": 15, "info": 5}

# Relative weights (normalized by their total). Categories not listed here (e.g. an unrecognized
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
    # Live click-through evidence (Reject doesn't stop tracking, etc.) is the
    # strongest evidence this module has — weighted accordingly. Weights are
    # normalized by their total in score_consent, so this needn't sum to 1.
    "runtime": 0.20,
}

_OTHER_CATEGORY = "other"
_OTHER_WEIGHT = 0.05

_PRIVACY_POLICY_LINK_RE = re.compile(r"privacy (policy|notice)", re.IGNORECASE)
_PRIVACY_POLICY_HREF_RE = re.compile(r"privacy[-_]?(policy|notice)", re.IGNORECASE)

# Rough CCPA signal: a "Do Not Sell/Share My Personal Information" link
# (required verbatim-ish wording under CCPA/CPRA for businesses that sell data).


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

    buckets = bucket_cookies(before.cookies)
    context_bits = []
    if buckets.consent_management:
        context_bits.append(f"{len(buckets.consent_management)} consent-management "
                            f"({', '.join(sorted({c.name for c in buckets.consent_management})[:3])})")
    if buckets.essential:
        context_bits.append(f"{len(buckets.essential)} essential/security "
                            f"({', '.join(sorted({c.name for c in buckets.essential})[:3])})")
    if buckets.functional:
        context_bits.append(f"{len(buckets.functional)} functional")
    if buckets.unknown:
        context_bits.append(f"{len(buckets.unknown)} unclassified (needs review, not counted as a failure)")
    context = ("Other cookies present: " + "; ".join(context_bits) + ".") if context_bits else ""

    if not buckets.consent_required:
        total = buckets.total
        detail = ("No analytics/marketing cookies were detected before consent"
                  + (f" ({total} cookie(s) present)." if total else " (no cookies were present)."))
        evidence = None
        if buckets.unknown:
            listed = [c.describe() for c in buckets.unknown[:_MAX_COOKIES_LISTED]]
            evidence = {
                "summary": context,
                "items": listed,
                "items_label": "Unclassified cookies to review",
            }
        return GdprCheck(key, label, True, detail + (" " + context if context and not evidence else ""),
                         evidence=evidence)

    by_category: Dict[str, int] = {}
    for c in buckets.consent_required:
        by_category[c.category] = by_category.get(c.category, 0) + 1
    breakdown = ", ".join(f"{n} {cat}" for cat, n in sorted(by_category.items()))

    listed = [c.describe() for c in buckets.consent_required[:_MAX_COOKIES_LISTED]]
    if len(buckets.consent_required) > _MAX_COOKIES_LISTED:
        listed.append(f"…and {len(buckets.consent_required) - _MAX_COOKIES_LISTED} more")

    return GdprCheck(
        key, label, False,
        f"{len(buckets.consent_required)} analytics/marketing cookie(s) were present before any consent action.",
        evidence={
            "summary": f"By category: {breakdown}." + (" " + context if context else ""),
            "items": listed,
            "items_label": "Analytics/marketing cookies present before consent",
        },
    )


def effective_buttons(
    static_buttons: ButtonsDetection, runtime_result: Optional["ConsentRuntimeResult"]
) -> ButtonsDetection:
    """
    The single control inventory every check reads. The rendered banner
    (consent.runtime) wins whenever the live pass saw it — it is what a
    visitor actually gets, and client-rendered CMPs never exist in raw
    HTML. Otherwise the banner-scoped static scan is used.
    """
    if runtime_result is not None and runtime_result.available and runtime_result.banner_detected:
        return runtime_result.buttons_detection()
    return static_buttons


_GROUPS = {
    "accept": ("accept_all", "accept"),
    "reject": ("reject_all", "reject", "reject_non_essential"),
    "manage": ("manage_preferences",),
}


def _describe_controls(buttons: ButtonsDetection, group: str) -> str:
    ctrls = [c for c in buttons.controls if c.action in _GROUPS[group]]
    if not ctrls:
        labels = {"accept": buttons.accept_labels, "reject": buttons.reject_labels,
                  "manage": buttons.manage_labels}[group]
        return ", ".join(f"'{l}'" for l in labels[:3]) or "—"
    return "; ".join(f"'{c.label}' (detected action: {c.action}, layer {c.layer})" for c in ctrls[:3])


def _controls_evidence(buttons: ButtonsDetection, group: str) -> Optional[dict]:
    ctrls = [c for c in buttons.controls if c.action in _GROUPS[group]]
    if not ctrls:
        return None
    return {
        "summary": f"Evidence: {ctrls[0].evidence}"
                   + (f" — container {buttons.container_hint}" if buttons.container_hint else "") + ".",
        "items": [f"Displayed text: “{c.label}” → Detected action: {c.action} "
                  f"({ACTION_LABELS.get(c.action, c.action)}) · {c.evidence}" for c in ctrls[:5]],
        "items_label": "Controls",
    }


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

    # One inventory decides every control check: the rendered banner when
    # the live pass saw it, otherwise the banner-scoped static markup scan.
    eff = effective_buttons(buttons, runtime_result)
    reject_layer = runtime_result.reject_layer if (runtime_result and runtime_result.available) else None
    if eff.source == "static" and eff.reject_found:
        reject_layer = 1

    accept_found = eff.accept_found
    reject_found = eff.reject_found or reject_layer == 2
    manage_found = eff.manage_found

    checks.append(GdprCheck(
        "accept_control", GDPR_CHECK_LABELS["accept_control"], accept_found,
        (f"Accept control found: {_describe_controls(eff, 'accept')}." if accept_found
         else "No accept control was found inside the consent banner."
         if eff.container_found else "No consent banner controls were found to evaluate."),
        evidence=_controls_evidence(eff, "accept") if accept_found else None,
    ))

    checks.append(GdprCheck(
        "reject_control", GDPR_CHECK_LABELS["reject_control"], reject_found,
        (f"Reject control found: {_describe_controls(eff, 'reject')}." if eff.reject_found
         else "A reject control exists, but only in the preference panel (second layer)."
         if reject_layer == 2
         else "No reject / necessary-only control was found inside the consent banner."
         if eff.container_found else "No consent banner controls were found to evaluate."),
        evidence=_controls_evidence(eff, "reject") if reject_found else None,
    ))

    has_reject_parity = accept_found and eff.reject_found and reject_layer != 2
    checks.append(GdprCheck(
        "reject_parity", GDPR_CHECK_LABELS["reject_parity"], has_reject_parity,
        "Reject is offered on the same banner layer as Accept." if has_reject_parity
        else "Reject is only reachable through the preference panel, while Accept is one click away."
        if reject_layer == 2 and accept_found
        else "Accept and reject aren't offered on equal footing (accept-only, or reject absent).",
    ))

    trackers_evidence = None
    observation = ""
    if network_result is not None and network_result.available:
        tag_managers = sorted({r.vendor for r in network_result.requests if r.category == "TAG_MANAGER" and r.vendor})
        if tag_managers:
            observation = (f" Observation: {', '.join(tag_managers)} loaded before consent — a tag manager "
                           "load is not by itself tracking; downstream collection requests were checked.")
        tracker_requests = network_result.tracker_requests
        if not behavior.blocks_scripts_pre_consent and tracker_requests:
            names = sorted({r.vendor or r.domain for r in tracker_requests})
            samples = sorted({r.short() for r in tracker_requests})[:8]
            trackers_evidence = {
                "summary": f"{len(tracker_requests)} analytics/advertising collection request(s) observed "
                           f"before consent ({', '.join(names)})." + observation,
                "items": samples,
                "items_label": "Collection requests before consent",
            }
    checks.append(GdprCheck(
        "trackers_blocked_pre_consent", GDPR_CHECK_LABELS["trackers_blocked_pre_consent"],
        behavior.blocks_scripts_pre_consent,
        ("Confirmed via live network capture: " if behavior.verified
         else "Based on the page's declared Consent Mode default only, not independently verified: ")
        + ("no analytics/advertising collection requests fired before consent." if behavior.blocks_scripts_pre_consent
           else "analytics/advertising tracking is not held back until consent.")
        + (observation if behavior.blocks_scripts_pre_consent else ""),
        evidence=trackers_evidence,
    ))

    checks.append(_cookies_before_consent_check(runtime_result))

    # Static detection + runtime verification: a Manage/Personalize control
    # only counts once clicking it actually opened a preference panel.
    panel_verified = (runtime_result.personalize_exposes_controls
                      if (runtime_result and runtime_result.available and runtime_result.manage_clicked) else None)
    granular_ok = manage_found and panel_verified is not False
    if not manage_found:
        granular_detail = "No manage/personalize option was found in the banner — only an all-or-nothing choice."
    elif panel_verified is True:
        granular_detail = (f"Preferences control {_describe_controls(eff, 'manage')} was clicked and a preference "
                           "panel with category choices appeared (runtime verified).")
    elif panel_verified is False:
        granular_detail = (f"Preferences control {_describe_controls(eff, 'manage')} was clicked, but no preference "
                           "panel with category choices appeared.")
    else:
        granular_detail = (f"A preferences control is offered in the banner: {_describe_controls(eff, 'manage')} "
                           "(not runtime verified).")
    checks.append(GdprCheck(
        "consent_is_granular", GDPR_CHECK_LABELS["consent_is_granular"], granular_ok,
        granular_detail,
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


# India's Digital Personal Data Protection Act, 2023 — technical indicators
# a website scan can observe. Reuses the technical checks above (no new
# page scanning); the DPDP framing is: notice before collection, a clear
# affirmative action, freedom to refuse, no processing before consent,
# and withdrawal as easy as giving consent.
DPDP_CHECK_ORDER = (
    "notice_available",
    "notice_purpose_stated",
    "grievance_contact",
    "notice_rights_described",
    "affirmative_consent_action",
    "refusal_available",
    "no_tracking_before_consent",
    "no_cookies_before_consent",
    "withdrawal_available",
    "refusal_blocks_tracking",
    "dpdp_referenced",
)

DPDP_CHECK_LABELS: Dict[str, str] = {
    "notice_available": "Privacy notice available",
    "affirmative_consent_action": "Clear affirmative consent action",
    "refusal_available": "Consent can be refused",
    "no_tracking_before_consent": "No tracking before consent",
    "no_cookies_before_consent": "No analytics/marketing cookies before consent",
    "withdrawal_available": "Consent withdrawal available",
    "refusal_blocks_tracking": "Refusal actually blocks tracking",
    "notice_purpose_stated": "Notice states what data is collected and why (s.5)",
    "grievance_contact": "Grievance / Data Protection Officer contact published (s.8(10))",
    "notice_rights_described": "Notice explains rights: access, correction, erasure, grievance (ss.11–14)",
    "dpdp_referenced": "Notice refers to the DPDP Act",
}

# DPDP notice checks — read from the privacy notice itself
# (consent.site_evidence). None = the notice could not be read.
_DPDP_NOTICE_RULES = {
    "notice_purpose_stated": (
        re.compile(r"\bpurposes?\b", re.I),
        re.compile(r"\bpersonal (?:data|information)\b|\bdata (?:we|that we) collect\b|\bcategories of (?:personal )?data\b", re.I),
    ),
    "grievance_contact": (
        re.compile(r"\bgrievance\b|\bdata protection officer\b|\bDPO\b|\bprivacy officer\b|\bnodal officer\b", re.I),
        re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|\bcontact\b", re.I),
    ),
    "notice_rights_described": (
        re.compile(r"\bright(?:s)? (?:to|of)\b|\byour rights\b", re.I),
        re.compile(r"\b(?:access|correct\w*|rectif\w*|eras\w*|delet\w*|withdraw\w*|nominat\w*|grievance)\b", re.I),
    ),
    "dpdp_referenced": (
        re.compile(r"\bDPDP\b|Digital\s+Personal\s+Data\s+Protection", re.I),
        None,
    ),
}
_DPDP_NOTICE_FAIL = {
    "notice_purpose_stated": "The privacy notice does not clearly say what personal data is collected and for what purpose.",
    "grievance_contact": "No Grievance Officer / Data Protection Officer contact was found in the privacy notice.",
    "notice_rights_described": "The privacy notice does not explain the data principal's rights (access, correction, erasure, grievance).",
    "dpdp_referenced": "The privacy notice does not mention the Digital Personal Data Protection Act, 2023.",
}

_DPDP_SOURCE = {
    "notice_available": "privacy_policy_available",
    "affirmative_consent_action": "accept_control",
    "refusal_available": "reject_control",
    "no_tracking_before_consent": "trackers_blocked_pre_consent",
    "no_cookies_before_consent": "cookies_blocked_pre_consent",
    "withdrawal_available": "consent_withdrawal_available",
    "refusal_blocks_tracking": "reject_blocks_tracking",
}

_DPDP_REQUIRED_FOR_COMPLIANCE = frozenset(DPDP_CHECK_ORDER) - {"refusal_blocks_tracking", "dpdp_referenced", "notice_rights_described"}


def _dpdp_notice_check(key: str, site_evidence) -> tuple:
    """(passed, evidence) for one notice check; passed None when no notice was read."""
    notice = getattr(site_evidence, "notice", None) if site_evidence is not None else None
    if notice is None or not (notice.text or "").strip():
        return None, {"reason": "The privacy notice could not be read automatically, so this was not tested."}
    first, second = _DPDP_NOTICE_RULES[key]
    text = notice.text
    m1 = first.search(text)
    ok = bool(m1) and (second is None or bool(second.search(text)))
    where = {"notice": notice.url}
    if ok:
        start = max(0, m1.start() - 60)
        return True, {**where, "excerpt": " ".join(text[start:m1.end() + 120].split())[:220]}
    return False, {**where, "reason": _DPDP_NOTICE_FAIL[key]}


def build_dpdp_assessment(technical: GdprAssessment, site_evidence=None) -> dict:
    """DPDP view: the technical consent checks plus checks read from the
    privacy notice itself (purpose, grievance contact, rights, DPDP
    reference) — returned as a JSON-ready dict."""
    checks: Dict[str, Optional[bool]] = {}
    evidence: Dict[str, dict] = {}
    for key in DPDP_CHECK_ORDER:
        if key in _DPDP_NOTICE_RULES:
            passed, ev = _dpdp_notice_check(key, site_evidence)
            checks[key] = passed
            if passed is not True and ev:
                evidence[key] = ev
            continue
        src = technical.get(_DPDP_SOURCE[key])
        checks[key] = src.passed if src else None
        if src and src.passed is not True:
            entry = dict(src.evidence) if src.evidence else {}
            if src.detail:
                entry["reason"] = src.detail
            if entry:
                evidence[key] = entry
    required = [checks[k] for k in DPDP_CHECK_ORDER if k in _DPDP_REQUIRED_FOR_COMPLIANCE]
    return {
        "checks": checks,
        "labels": dict(DPDP_CHECK_LABELS),
        "order": list(DPDP_CHECK_ORDER),
        "evidence": evidence,
        "compliant": bool(required) and all(v is True for v in required),
        "status": ("pass" if all(v is True for v in required)
                   else "fail" if any(v is False for v in required) else "not_tested"),
    }


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

    # Region detection + which frameworks were assessed (consent.region).
    # gdpr_checks / ccpa_checks above are only populated when that framework
    # is applicable; an empty dict + applicability.frameworks[*].status ==
    # "not_assessed" means "not assessed", never "failed".
    applicability: Dict[str, object] = field(default_factory=dict)
    # Framework-neutral technical consent scan: the rendered banner, its
    # control inventory (label / detected action / evidence), the technical
    # checks, and the classified pre-consent network/cookie evidence.
    technical_scan: Dict[str, object] = field(default_factory=dict)

    # Phase 2: the region engine's output as first-class columns
    # (consent.region.RegionResult) + the consent-control inventory.
    detected_region: str = "UNKNOWN"
    region_confidence: str = "low"
    region_evidence: List[str] = field(default_factory=list)
    applicable_frameworks: List[str] = field(default_factory=list)
    applicability_status: str = "not_determined"
    consent_controls: List[dict] = field(default_factory=list)


def detect_privacy_policy(page: ParsedPage) -> Optional[str]:
    """Returns the absolute-or-relative href of a privacy policy link, if any is found."""
    for tag in page.anchor_tags:
        text = tag.get_text(strip=True) or ""
        href = tag.get("href") or ""
        if _PRIVACY_POLICY_LINK_RE.search(text) or _PRIVACY_POLICY_HREF_RE.search(href):
            return href or None
    return None


def detect_ccpa_link(page: ParsedPage) -> bool:
    """Back-compat wrapper — the signal now lives in consent.ccpa."""
    return detect_do_not_sell_link(page)


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
    target_region: Optional[str] = None,
    region: Optional[RegionResult] = None,
    ccpa_signals: Optional[CcpaSignals] = None,
    scan_meta: Optional[dict] = None,
    site_evidence=None,
    # Phase 1 keyword, kept for callers that still pass it.
    applicability: Optional[RegionResult] = None,
) -> ConsentSummary:
    """
    Assembles a ConsentSummary ready for models.consent.Consent(**vars(summary)).

    Flow:
        region detected  →  applicable frameworks  →  run applicable assessment(s)

    The ten technical checks (GDPR_CHECK_ORDER) are always computed — they
    are the framework-neutral *technical consent scan* and are stored in
    `technical_scan`. They are only *interpreted* as a GDPR assessment
    (gdpr_checks / gdpr_compliant) when GDPR applies; CCPA's six checks
    only run when a California candidate is detected; DPDP only for India.
    When no region can be established, regional compliance is
    "not assessed" — no GDPR/CCPA pass or fail is produced at all.
    """
    applicability = region or applicability or detect_region(page.url, page, target_region)
    ccpa_signals = ccpa_signals or detect_ccpa_signals(page)

    privacy_policy_url = detect_privacy_policy(page)
    if privacy_policy_url is None and getattr(site_evidence, "notice", None) is not None:
        # No privacy link on the homepage, but the notice was found one level
        # down (e.g. a PDF linked from a "Policies" page).
        privacy_policy_url = site_evidence.notice.url
    ccpa_link_found = ccpa_signals.do_not_sell_link
    privacy_choices = ccpa_signals.privacy_choices
    gpc_honored = ccpa_signals.gpc_handling

    technical = build_gdpr_assessment(
        banner_detected=banner_detected,
        buttons=buttons,
        behavior=behavior,
        preferences=preferences,
        privacy_policy_url=privacy_policy_url,
        cookie_summary=cookie_summary,
        runtime_result=runtime_result,
        network_result=network_result,
    )

    assessments: Dict[str, dict] = {}

    gdpr_checks: Dict[str, Optional[bool]] = {}
    gdpr_evidence: Dict[str, dict] = {}
    gdpr_compliant = False
    if applicability.applies(FW_GDPR):
        gdpr_checks = technical.as_dict()
        gdpr_evidence = technical.as_evidence_dict()
        gdpr_compliant = technical.compliant
        assessments[FW_GDPR] = {
            "compliant": gdpr_compliant,
            "status": _status(technical.checks, _REQUIRED_FOR_COMPLIANCE),
            "passed": technical.passed_count, "tested": technical.tested_count,
        }

    ccpa_checks: Dict[str, Optional[bool]] = {}
    ccpa_compliant = False
    if applicability.applies(FW_CCPA):
        ccpa_assessment = build_ccpa_assessment(
            privacy_policy_url=privacy_policy_url,
            ccpa_link_found=ccpa_link_found,
            privacy_choices=privacy_choices,
            preferences=preferences,
            gpc_honored=gpc_honored,
            runtime_result=runtime_result,
        )
        ccpa_checks = ccpa_assessment.as_dict()
        ccpa_compliant = ccpa_assessment.compliant
        assessments[FW_CCPA] = {
            "compliant": ccpa_compliant,
            "status": _status(ccpa_assessment.checks, _CCPA_REQUIRED_FOR_COMPLIANCE),
            "passed": ccpa_assessment.passed_count, "tested": ccpa_assessment.tested_count,
            "details": {c.key: c.detail for c in ccpa_assessment.checks},
        }

    if applicability.applies(FW_DPDP):
        assessments[FW_DPDP] = build_dpdp_assessment(technical, site_evidence)

    runtime_available = bool(runtime_result and runtime_result.available)
    runtime_tested = bool(
        runtime_result and runtime_result.available
        and (runtime_result.accept_clicked or runtime_result.reject_clicked)
    )

    banner_found, _ = resolve_banner_detection(banner_detected, runtime_result)

    return ConsentSummary(
        has_cookie_banner=banner_found,
        banner_blocks_scripts_pre_consent=behavior.blocks_scripts_pre_consent,
        gdpr_compliant=gdpr_compliant,
        gdpr_checks=gdpr_checks,
        gdpr_check_evidence=gdpr_evidence,
        ccpa_compliant=ccpa_compliant,
        ccpa_checks=ccpa_checks,
        privacy_policy_found=privacy_policy_url is not None,
        privacy_policy_url=privacy_policy_url,
        cookies_detected=cookie_summary.cookies_detected,
        third_party_trackers=cookie_summary.third_party_trackers,
        consent_score=score_result.overall,
        runtime_available=runtime_available,
        runtime_tested=runtime_tested,
        runtime_result=_serialize_runtime(runtime_result),
        applicability=applicability.as_dict(assessments),
        technical_scan=_with_scan_meta(build_technical_scan(
            technical=technical, buttons=buttons, runtime_result=runtime_result,
            network_result=network_result, banner_found=banner_found,
        ), scan_meta, ccpa_signals, preferences),
        detected_region=applicability.region,
        region_confidence=applicability.confidence,
        region_evidence=applicability.evidence,
        applicable_frameworks=applicability.applicable_frameworks,
        applicability_status=applicability.applicability_status,
        consent_controls=[
            {"label": c.label, "action": c.action, "evidence": c.evidence, "layer": c.layer}
            for c in effective_buttons(buttons, runtime_result).controls
        ],
    )


def _with_scan_meta(scan: dict, scan_meta: Optional[dict], ccpa_signals: CcpaSignals,
                    preferences: PreferencesDetection) -> dict:
    scan["ccpa_signals"] = ccpa_signals.as_dict()
    scan["preferences"] = {
        "static_link_found": preferences.link_found,
        "static_trigger_found": preferences.trigger_found,
        "link_text": preferences.link_text,
        "panel_verified": getattr(preferences, "panel_verified", None),
        "panel_toggle_count": getattr(preferences, "panel_toggle_count", None),
    }
    if scan_meta:
        scan["scan"] = scan_meta
    return scan


def _status(checks, required_keys) -> str:
    required = [c for c in checks if c.key in required_keys]
    if required and all(c.passed is True for c in required):
        return "pass"
    if any(c.passed is False for c in required):
        return "fail"
    return "not_tested"


def _serialize_runtime(runtime_result) -> Optional[dict]:
    if not runtime_result:
        return None
    data = dataclasses.asdict(runtime_result)
    # Keep the stored row small and useful: per-request detail is summarized
    # in network_summary; keep only confirmed-tracking + vendor requests here.
    for state in ("before_consent", "after_reject", "before_accept", "after_accept"):
        cap = getattr(runtime_result, state, None)
        if cap is None or state not in data:
            continue
        data[state]["requests"] = [
            {"url": r.url, "domain": r.domain, "category": r.category, "vendor": r.vendor,
             "activity": r.activity, "is_tracking": r.is_tracking, "resource_type": r.resource_type}
            for r in cap.requests if r.category not in ("FIRST_PARTY", "CONTENT_CDN", "FONT", "UNKNOWN")
        ][:150]
        data[state]["cookie_buckets"] = {
            k: [c.describe() for c in v]
            for k, v in vars(bucket_cookies(cap.cookies)).items()
        }
    return data


def build_technical_scan(
    *,
    technical: GdprAssessment,
    buttons: ButtonsDetection,
    runtime_result: Optional["ConsentRuntimeResult"],
    network_result: Optional["PreConsentNetworkResult"],
    banner_found: bool,
) -> dict:
    """Framework-neutral technical consent scan for the report (JSON-ready)."""
    from consent.network import summarize_requests  # local: keeps module import light

    eff = effective_buttons(buttons, runtime_result)
    runtime_ok = bool(runtime_result and runtime_result.available)

    banner: Dict[str, object] = {
        "detected": banner_found,
        "source": "rendered" if eff.source == "runtime" else ("static_markup" if eff.container_found else None),
        "container": eff.container_hint,
        "detected_via": eff.detected_via,
    }
    if runtime_ok and runtime_result.banner:
        banner.update({
            "frame": runtime_result.banner.get("frame"),
            "is_overlay": runtime_result.banner.get("is_overlay"),
            "text_excerpt": runtime_result.banner.get("text_excerpt"),
        })

    network: Dict[str, object] = {}
    if network_result is not None and network_result.available:
        network["before_consent"] = summarize_requests(network_result.requests)
    elif runtime_ok and runtime_result.network_summary.get("before_consent"):
        network["before_consent"] = runtime_result.network_summary["before_consent"]
    if runtime_ok:
        for k in ("after_reject", "after_accept"):
            if k in runtime_result.network_summary:   # an empty capture is evidence too ("no requests")
                network[k] = runtime_result.network_summary[k]

    cookies: Dict[str, object] = {}
    if runtime_ok and runtime_result.before_consent.available:
        b = bucket_cookies(runtime_result.before_consent.cookies)
        cookies = {k: [c.describe() for c in v] for k, v in vars(b).items()}

    return {
        "banner": banner,
        "controls": [c.as_dict() for c in eff.controls],
        "checks": technical.as_dict(),
        "check_details": {c.key: c.detail for c in technical.checks},
        "evidence": technical.as_evidence_dict(),
        "network": network,
        "cookies_before_consent": cookies,
        "reject_layer": runtime_result.reject_layer if runtime_ok else (1 if eff.reject_found else None),
    }
