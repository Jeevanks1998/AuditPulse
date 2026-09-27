"""
images/image_score.py

Turns the flat finding lists from images/optimizer.py, alt.py,
lazyload.py, and broken.py into a single weighted 0-100 score with a
per-category breakdown — same shape as seo/seo_score.py and
ux/ux_score.py, so it drops into Audit.breakdown / AuditStatsOut.
breakdown as breakdown["images"] alongside the other module scores.

"broken" is weighted heaviest since a broken image is a visible defect
regardless of any other image-quality concern; "optimization" is next
since format/CLS issues affect every visitor, while "alt" and
"lazyload" are comparatively lower-stakes refinements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

MODULE = "images"

SEVERITY_PENALTY = {"critical": 25, "warning": 12, "info": 4}

# Must sum to 1.0.
CATEGORY_WEIGHTS: Dict[str, float] = {
    "broken": 0.35,
    "optimization": 0.30,
    "alt": 0.20,
    "lazyload": 0.15,
}

_OTHER_CATEGORY = "other"
_OTHER_WEIGHT = 0.05


@dataclass
class ImageScoreResult:
    overall: int
    breakdown: Dict[str, int] = field(default_factory=dict)
    counts_by_severity: Dict[str, int] = field(default_factory=dict)
    findings: List[dict] = field(default_factory=list)


def score_images(findings: List[dict]) -> ImageScoreResult:
    """Scores a flat list of finding dicts (images/* run_*_checks output) into an overall score."""
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

    return ImageScoreResult(
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
