"""
accessibility/accessibility_score.py

Turns the flat finding lists every other accessibility/ module returns
into a single weighted 0-100 score with a per-category breakdown — the
same shape Audit.breakdown["accessibility"] and AuditStatsOut.breakdown
already carry, so this can drop straight into services.audit_service in
place of the `breakdown["accessibility"] = random.randint(75, 96)`
placeholder.

Scoring model: every category (axe, pa11y, contrast, aria, keyboard,
labels, headings) starts at 100 and loses points per finding by
severity. Categories with no findings at all stay at 100 rather than
being penalized for absence of data — this matters here more than
elsewhere, since axe/pa11y are both allowed to contribute nothing (no
PSI key configured, pa11y not installed locally) without dragging the
score down. When Lighthouse's own accessibility category score is
available (accessibility.axe.AxeAuditResult.category_score), it's
blended in directly, the same way performance/performance_score.py
blends Lighthouse's performance score — mirrors what Google's own
scoring model weighs, on top of our own finding-based penalties.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

MODULE = "accessibility"

SEVERITY_PENALTY = {"critical": 25, "warning": 12, "info": 4}

# Must sum to 1.0. Categories not listed here (e.g. an unrecognized
# `category` value on a finding) are folded into "other" at a small
# default weight so nothing is silently dropped from the overall score.
CATEGORY_WEIGHTS: Dict[str, float] = {
    "axe": 0.25,       # broadest single-pass coverage (full axe-core ruleset via Lighthouse)
    "labels": 0.16,    # form/button/link accessible names — frequent, high-impact failures
    "aria": 0.14,
    "contrast": 0.13,
    "keyboard": 0.13,
    "headings": 0.10,
    "pa11y": 0.09,     # optional local tool; lower weight since it's often unavailable
}

_OTHER_CATEGORY = "other"
_OTHER_WEIGHT = 0.05

# How much weight Lighthouse's own 0-100 accessibility category score gets
# against the findings-based score, when an axe.py PSI run is actually available.
LIGHTHOUSE_BLEND_WEIGHT = 0.5


@dataclass
class AccessibilityScoreResult:
    overall: int
    breakdown: Dict[str, int] = field(default_factory=dict)
    counts_by_severity: Dict[str, int] = field(default_factory=dict)
    findings: List[dict] = field(default_factory=list)
    lighthouse_accessibility_score: Optional[int] = None


def score_accessibility(
    findings: List[dict],
    lighthouse_accessibility_score: Optional[int] = None,
) -> AccessibilityScoreResult:
    """
    Scores a flat list of finding dicts (as returned by
    accessibility.axe.check_axe_audits, accessibility.pa11y.run_pa11y,
    and the page-level contrast/aria/keyboard/labels/heading checks,
    concatenated across a crawl) into an overall score plus per-category
    breakdown. Pass `lighthouse_accessibility_score`
    (accessibility.axe.AxeAuditResult.category_score) when available to
    anchor the overall score against Lighthouse/axe-core's own weighting
    model, not just our finding counts.
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

    findings_based_score = round(weighted_sum / weight_total) if weight_total else 100

    if lighthouse_accessibility_score is not None:
        overall = round(
            lighthouse_accessibility_score * LIGHTHOUSE_BLEND_WEIGHT
            + findings_based_score * (1 - LIGHTHOUSE_BLEND_WEIGHT)
        )
    else:
        overall = findings_based_score

    counts_by_severity: Dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
    for finding in findings:
        severity = finding.get("severity", "info")
        counts_by_severity[severity] = counts_by_severity.get(severity, 0) + 1

    return AccessibilityScoreResult(
        overall=overall,
        breakdown=breakdown,
        counts_by_severity=counts_by_severity,
        findings=findings,
        lighthouse_accessibility_score=lighthouse_accessibility_score,
    )


def _score_category(category_findings: List[dict]) -> int:
    score = 100
    for finding in category_findings:
        score -= SEVERITY_PENALTY.get(finding.get("severity", "info"), SEVERITY_PENALTY["info"])
    return max(0, score)
