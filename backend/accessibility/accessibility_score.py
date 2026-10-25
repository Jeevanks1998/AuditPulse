"""
Turns accessibility findings into a 0-100 score with a per-category breakdown.

Each category starts at 100 and loses points per finding. Categories with no
data (e.g. no PageSpeed key) stay at 100. When Lighthouse's own accessibility
score is available it is blended in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

MODULE = "accessibility"

SEVERITY_PENALTY = {"critical": 25, "warning": 12, "info": 4}

# Must sum to 1.0. Unknown categories count as "other".
CATEGORY_WEIGHTS: Dict[str, float] = {
    "axe": 0.25,       # widest coverage
    "labels": 0.16,    # missing accessible names are common and serious
    "aria": 0.14,
    "contrast": 0.13,
    "keyboard": 0.13,
    "headings": 0.10,
    "pa11y": 0.09,     # often not installed, so lower weight
}

_OTHER_CATEGORY = "other"
_OTHER_WEIGHT = 0.05

# Weight of Lighthouse's own score when it is available.
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
    """Scores accessibility findings. Pass Lighthouse's score when available to blend it in."""
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
