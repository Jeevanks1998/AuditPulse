"""
config/compliance_profiles.py

Private, backend-only configuration. This module is the one place that
knows about AuditPulse's *internal* compliance bar — the extra,
org-specific policy layered on top of the legal minimum — and it is the
only place allowed to combine that with the detected regional framework
to produce a final verdict.

    Regional Framework                 (consent.consent_score —
        (GDPR / UK GDPR /               resolve_applicable_frameworks,
         Swiss FADP / CCPA)             build_gdpr_assessment/build_ccpa_assessment)
            +
    Internal Compliance Requirements   (this module — private, not
        (stricter thresholds,           derived from statute, never
         sign-off checks, etc.)         serialized to the browser)
            v
    Final Assessment                   (ComplianceStatus — the ONLY
                                         thing that crosses to the
                                         frontend)

Why this is split out from consent/consent_score.py: that module's
GdprAssessment/CcpaAssessment checks are all legally-grounded (Art.
4(11), CNIL/ICO guidance, CCPA/CPRA text, ...) — safe to explain in a
report because they cite an external requirement. The internal
requirements here are AuditPulse policy, not law (e.g. "we don't sign
off as compliant unless the live click-through pass actually verified
behavior, a bare static-only pass isn't good enough for us internally").
Mixing the two into the checks list the frontend already renders would
leak *why* AuditPulse considers something insufficient — i.e. whose bar
it failed to clear, legal or internal — which is not the browser's
business. So:

  - consent/consent_score.py stays the source of truth for the legal
    checks and keeps returning them in full (report/audit trail use,
    already-authenticated internal surfaces).
  - This module is backend-only, imported by services/schemas that build
    the final verdict, and NEVER imported by anything that hands a
    finding-level payload to the frontend.
  - The frontend (and any public-facing schema) gets exactly one thing
    per framework: `ComplianceStatus`. It never sees which internal
    requirement (if any) is the reason a site landed on NEEDS_REVIEW
    instead of COMPLIANT — just the label.

Nothing in this file does any page-scanning or detection itself; it only
consumes the already-computed GdprAssessment/CcpaAssessment plus a
handful of already-computed signals (consent_score, runtime_tested).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional


class ComplianceStatus(str, Enum):
    """
    The complete, final vocabulary the browser is ever shown for a
    regional compliance verdict. Nothing else — no per-check keys, no
    weight, no mention of which requirement (legal or internal) drove
    the result — crosses this boundary.
    """
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non-compliant"
    NEEDS_REVIEW = "needs review"
    NOT_ASSESSED = "not assessed"


@dataclass(frozen=True)
class InternalComplianceRequirements:
    """
    One framework's *internal* bar — never derived from statute, never
    shown to the browser, and independent of consent.consent_score's
    legal check set so the two can be tuned separately (legal checks
    change when the law does; these change when internal policy does).

    min_consent_score:
        AuditPulse won't sign off a framework as fully COMPLIANT below
        this score even if every legal check technically passed — a
        stricter internal floor than "meets the legal minimum".
    require_runtime_verification:
        If True, a site that passed every required legal check using
        only the static pass (no live click-through / Playwright
        confirmation) is held at NEEDS_REVIEW rather than promoted to
        COMPLIANT — internal policy doesn't consider a compliance claim
        final until it's been behaviorally verified, not just inferred
        from markup.
    owner:
        Which internal team/policy this bar belongs to. Purely for
        engineers reading this file and for internal audit-trail
        logging — this must never be serialized into any
        frontend-facing response.
    """
    min_consent_score: int
    require_runtime_verification: bool
    owner: str = "internal"


# ---------------------------------------------------------------------------
# Internal requirements, keyed the same way
# consent.consent_score.REGIONAL_SCORING_PROFILES / resolve_applicable_
# frameworks name frameworks ("GDPR" covers GDPR/UK GDPR/Swiss FADP,
# which all share one legal check set; "CCPA" covers CCPA/CPRA).
#
# These numbers are policy, not law — change them here, not by editing
# the legal check set in consent/consent_score.py.
# ---------------------------------------------------------------------------
INTERNAL_COMPLIANCE_REQUIREMENTS: Dict[str, InternalComplianceRequirements] = {
    "GDPR": InternalComplianceRequirements(
        min_consent_score=85,
        require_runtime_verification=True,
        owner="privacy-eng",
    ),
    "CCPA": InternalComplianceRequirements(
        min_consent_score=80,
        require_runtime_verification=True,
        owner="privacy-eng",
    ),
}

# Fallback used if a framework name shows up here that isn't configured
# above (e.g. a new regional framework added to consent_score before its
# internal bar has been tuned) — deliberately conservative (nothing
# waived) rather than silently skipping the internal layer.
_DEFAULT_INTERNAL_REQUIREMENTS = InternalComplianceRequirements(
    min_consent_score=80,
    require_runtime_verification=True,
    owner="internal",
)


def _internal_requirements_for(framework_name: str) -> InternalComplianceRequirements:
    return INTERNAL_COMPLIANCE_REQUIREMENTS.get(framework_name, _DEFAULT_INTERNAL_REQUIREMENTS)


def resolve_final_assessment(
    *,
    framework_name: Optional[str],
    legal_applicable: bool,
    legal_compliant: Optional[bool],
    consent_score: int,
    runtime_tested: bool,
) -> ComplianceStatus:
    """
    Combines the regional (legal) verdict with AuditPulse's internal
    requirements into the single status the browser is allowed to see.

    Inputs are the already-computed outputs of the regional-framework
    layer (consent.consent_score) plus a couple of already-computed
    signals — nothing here re-inspects the page or a finding list.

      framework_name     "GDPR" / "UK GDPR" / "Swiss FADP" / "CCPA/CPRA",
                          or None when no regional framework applies.
      legal_applicable    GdprAssessment.applicable / CcpaAssessment
                          .applicable — whether this audit's region put
                          it in scope for the framework at all.
      legal_compliant     GdprAssessment.compliant / CcpaAssessment
                          .compliant — True/False/None. None here means
                          "not assessed" and must never be treated as a
                          failure.
      consent_score       The 0-100 weighted score from
                          consent.consent_score.score_consent — checked
                          against the internal min_consent_score floor.
      runtime_tested      Whether the live click-through pass actually
                          ran and clicked something (consent.runtime) —
                          checked against require_runtime_verification.

    Resolution order:
      1. No regional framework applies at all -> NOT_ASSESSED. An
         internal bar can only ever tighten a legal verdict that
         exists; it can't manufacture a verdict for a framework that
         was never in scope.
      2. Fails the legal minimum -> NON_COMPLIANT. Internal policy is a
         *stricter* bar layered on top of the law, never a looser one,
         so a legal failure is always a final failure regardless of
         what the internal requirements say.
      3. Meets the legal minimum but not every internal requirement
         (score floor and/or runtime verification, whichever this
         framework's profile requires) -> NEEDS_REVIEW. Legally fine,
         but not yet at the bar AuditPulse signs off on automatically —
         a human should look at it before it's called compliant.
      4. Meets both the legal minimum and every internal requirement
         -> COMPLIANT.
    """
    normalized_framework = _normalize_framework_name(framework_name)

    if not legal_applicable or legal_compliant is None or normalized_framework is None:
        return ComplianceStatus.NOT_ASSESSED

    if legal_compliant is False:
        return ComplianceStatus.NON_COMPLIANT

    requirements = _internal_requirements_for(normalized_framework)

    meets_score_floor = consent_score >= requirements.min_consent_score
    meets_runtime_bar = runtime_tested or not requirements.require_runtime_verification

    if meets_score_floor and meets_runtime_bar:
        return ComplianceStatus.COMPLIANT

    return ComplianceStatus.NEEDS_REVIEW


# GDPR, UK GDPR and Swiss FADP all resolve to the "GDPR" internal profile
# above — they share the exact same legal check set in consent_score.py,
# just under different display names per region.
_GDPR_FAMILY_DISPLAY_NAMES = frozenset({"GDPR", "UK GDPR", "Swiss FADP"})


def _normalize_framework_name(framework_name: Optional[str]) -> Optional[str]:
    if framework_name in _GDPR_FAMILY_DISPLAY_NAMES:
        return "GDPR"
    if framework_name == "CCPA/CPRA":
        return "CCPA"
    return None


@dataclass(frozen=True)
class ComplianceAssessment:
    """
    The full public-facing verdict for one framework — exactly the two
    fields the docstring at the top of this file promises the browser:
    which framework was evaluated (its display name, e.g. "GDPR", "UK
    GDPR", "Swiss FADP", "CCPA/CPRA" — never which internal policy team
    set the bar behind it) and the final status. Safe to serialize
    as-is; nothing else needs to be attached here.
    """
    framework: Optional[str]
    status: ComplianceStatus = field(default=ComplianceStatus.NOT_ASSESSED)


def build_gdpr_final_assessment(
    *,
    framework_name: Optional[str],
    applicable: bool,
    compliant: Optional[bool],
    consent_score: int,
    runtime_tested: bool,
) -> ComplianceAssessment:
    """Convenience wrapper around resolve_final_assessment for the GDPR-family verdict."""
    status = resolve_final_assessment(
        framework_name=framework_name,
        legal_applicable=applicable,
        legal_compliant=compliant,
        consent_score=consent_score,
        runtime_tested=runtime_tested,
    )
    return ComplianceAssessment(framework=framework_name if applicable else None, status=status)


def build_ccpa_final_assessment(
    *,
    applicable: bool,
    compliant: Optional[bool],
    consent_score: int,
    runtime_tested: bool,
) -> ComplianceAssessment:
    """Convenience wrapper around resolve_final_assessment for the CCPA/CPRA verdict."""
    framework_name = "CCPA/CPRA" if applicable else None
    status = resolve_final_assessment(
        framework_name=framework_name,
        legal_applicable=applicable,
        legal_compliant=compliant,
        consent_score=consent_score,
        runtime_tested=runtime_tested,
    )
    return ComplianceAssessment(framework=framework_name, status=status)
