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
from consent.consent_mode import ConsentModeDetection
from cookies.storage import CookieSummary

if TYPE_CHECKING:  # avoid importing consent.runtime at module load time
    from consent.runtime import ConsentRuntimeResult

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


@dataclass
class ConsentSummary:
    """Field-for-field match with models.consent.Consent, minus audit_id/id/created_at."""
    has_cookie_banner: bool = False
    banner_blocks_scripts_pre_consent: bool = False
    gdpr_compliant: bool = False
    ccpa_compliant: bool = False
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
    preferences_found: bool,
    score_result: ConsentScoreResult,
    runtime_result: Optional["ConsentRuntimeResult"] = None,
) -> ConsentSummary:
    """
    Assembles a ConsentSummary ready to pass straight into
    models.consent.Consent(**vars(summary), audit_id=...). Takes the
    individual detect_*()/evaluate_*() results rather than re-deriving
    them, since consent.analyze_page already computed all of them once.

    GDPR-compliant is judged on the combination that actually matters
    to a regulator: a banner exists, it offers reject with equal
    footing to accept, scripts are genuinely held back until consent,
    and a privacy policy is discoverable. CCPA compliance is judged
    more narrowly on its own required disclosure (a "Do Not Sell/Share"
    link) plus the same privacy-policy discoverability baseline —
    GDPR's stricter opt-in banner isn't a CCPA requirement, so the two
    verdicts are allowed to disagree.
    """
    privacy_policy_url = detect_privacy_policy(page)
    ccpa_link_found = detect_ccpa_link(page)

    gdpr_compliant = (
        banner_detected
        and buttons.has_reject_parity
        and behavior.blocks_scripts_pre_consent
        and privacy_policy_url is not None
    )
    ccpa_compliant = ccpa_link_found and privacy_policy_url is not None

    runtime_available = bool(runtime_result and runtime_result.available)
    # "Tested" means the engine actually got as far as clicking a button —
    # an available-but-empty pass (e.g. no banner to click) should still
    # show as "not tested" to the report, not as a silent pass/fail.
    runtime_tested = bool(
        runtime_result and runtime_result.available
        and (runtime_result.accept_clicked or runtime_result.reject_clicked)
    )

    return ConsentSummary(
        has_cookie_banner=banner_detected,
        banner_blocks_scripts_pre_consent=behavior.blocks_scripts_pre_consent,
        gdpr_compliant=gdpr_compliant,
        ccpa_compliant=ccpa_compliant,
        privacy_policy_found=privacy_policy_url is not None,
        privacy_policy_url=privacy_policy_url,
        cookies_detected=cookie_summary.cookies_detected,
        third_party_trackers=cookie_summary.third_party_trackers,
        consent_score=score_result.overall,
        runtime_available=runtime_available,
        runtime_tested=runtime_tested,
        runtime_result=dataclasses.asdict(runtime_result) if runtime_result else None,
    )
