"""
ux/ux_score.py

Turns the flat finding lists every other ux/ module returns into a
single weighted 0-100 score with a per-category breakdown — same shape
as accessibility/accessibility_score.py and security/security_score.py,
so this drops in wherever a `breakdown["ux"]` entry is needed (there's
no placeholder for it yet in services.audit_service.EMPTY_BREAKDOWN /
run_audit_pipeline — add `"ux": 0` there and one line writing
`breakdown["ux"] = result.score.overall` alongside the other three
when wiring this in).

Scoring model: every category starts at 100 and loses points per
finding by severity, same penalty scale as accessibility/security so a
"critical" means the same thing across every module in this codebase.
UX findings skew softer than accessibility/security ones by nature —
"generic button label" is a real but minor issue, never a blocker — so
nothing in ux/ emits "critical", and the category weights below are
close to even rather than one category dominating, since none of
navigation/typography/colors/buttons/spacing/readability structurally
outweighs the others the way e.g. security/ssl.py does in security/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

MODULE = "ux"

SEVERITY_PENALTY = {"critical": 25, "warning": 10, "info": 3}

# Must sum to 1.0.
CATEGORY_WEIGHTS: Dict[str, float] = {
    "navigation": 0.20,
    "readability": 0.20,
    "buttons": 0.18,
    "typography": 0.17,
    "spacing": 0.13,
    "colors": 0.12,
}

_OTHER_CATEGORY = "other"
_OTHER_WEIGHT = 0.05


@dataclass
class UxScoreResult:
    overall: int
    breakdown: Dict[str, int] = field(default_factory=dict)
    counts_by_severity: Dict[str, int] = field(default_factory=dict)
    findings: List[dict] = field(default_factory=list)


def score_ux(findings: List[dict]) -> UxScoreResult:
    """
    Scores a flat list of finding dicts (as returned by
    ux.navigation, ux.typography, ux.colors, ux.buttons, ux.spacing,
    ux.readability, concatenated across a crawl) into an overall score
    plus per-category breakdown. Categories with no findings stay at
    100 rather than being penalized for absence of data, same
    reasoning as accessibility_score.py.
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

    return UxScoreResult(
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
