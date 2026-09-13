"""
performance/performance_score.py

Turns the flat finding lists from pagespeed.py (field_data),
lighthouse.py (lab_data), and optimization.py (optimization) into a
single weighted 0-100 score with a per-category breakdown — the same
shape Audit.breakdown["performance"] / AuditStatsOut.breakdown already
carry, so this drops straight into services.audit_service in place of
the `breakdown["performance"] = random.randint(70, 97)` placeholder.

When Lighthouse's own performance category score is available, it's
blended in directly (LIGHTHOUSE_BLEND_WEIGHT) alongside the
findings-based penalty score — Lighthouse's score already accounts for
metric weighting Google tunes over time, so it's worth more than
reconstructing an equivalent from our own audit list, but the
findings-based side still matters for consistency with how every other
module (seo.seo_score, and this same shape) scores things, and it's all
we have when no Lighthouse data exists at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

MODULE = "performance"

SEVERITY_PENALTY = {"critical": 25, "warning": 12, "info": 4}

# Must sum to 1.0. A finding with an unrecognized `category` value folds
# into "other" at a small default weight so nothing is silently dropped.
CATEGORY_WEIGHTS: Dict[str, float] = {
    "field_data": 0.35,
    "lab_data": 0.35,
    "optimization": 0.30,
}

_OTHER_CATEGORY = "other"
_OTHER_WEIGHT = 0.05

# How much weight Lighthouse's own 0-100 performance score gets against
# the findings-based score, when a Lighthouse run is actually available.
LIGHTHOUSE_BLEND_WEIGHT = 0.6


@dataclass
class PerformanceScoreResult:
    overall: int
    breakdown: Dict[str, int] = field(default_factory=dict)
    counts_by_severity: Dict[str, int] = field(default_factory=dict)
    findings: List[dict] = field(default_factory=list)
    lighthouse_score: Optional[int] = None


def score_performance(findings: List[dict], lighthouse_score: Optional[int] = None) -> PerformanceScoreResult:
    """
    Scores a flat list of finding dicts (as returned by
    performance.pagespeed.check_field_data,
    performance.lighthouse.check_lighthouse, and
    performance.optimization.check_optimizations, concatenated) into an
    overall score plus per-category breakdown. Pass `lighthouse_score`
    (performance.lighthouse.LabMetrics.performance_score, i.e. Lighthouse's
    own 0-100 category score) when available to anchor the overall score
    against Lighthouse's own weighting model, not just our finding counts.
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

    if lighthouse_score is not None:
        overall = round(
            lighthouse_score * LIGHTHOUSE_BLEND_WEIGHT
            + findings_based_score * (1 - LIGHTHOUSE_BLEND_WEIGHT)
        )
    else:
        overall = findings_based_score

    counts_by_severity: Dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
    for finding in findings:
        severity = finding.get("severity", "info")
        counts_by_severity[severity] = counts_by_severity.get(severity, 0) + 1

    return PerformanceScoreResult(
        overall=overall,
        breakdown=breakdown,
        counts_by_severity=counts_by_severity,
        findings=findings,
        lighthouse_score=lighthouse_score,
    )


def _score_category(category_findings: List[dict]) -> int:
    score = 100
    for finding in category_findings:
        score -= SEVERITY_PENALTY.get(finding.get("severity", "info"), SEVERITY_PENALTY["info"])
    return max(0, score)
