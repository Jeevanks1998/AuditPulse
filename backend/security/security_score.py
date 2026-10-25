"""
Turns security findings into a 0-100 score. SSL and HTTPS weigh most.
Categories with no findings score 100; the SSL category is skipped for
http URLs (no handshake was possible).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

MODULE = "security"

SEVERITY_PENALTY = {"critical": 30, "warning": 12, "info": 3}

# Must sum to 1.0.
CATEGORY_WEIGHTS: Dict[str, float] = {
    "ssl": 0.25,            # certificate trust/expiry/protocol strength
    "https": 0.20,          # is the site even served over, and enforcing, HTTPS
    "headers": 0.20,        # clickjacking/sniffing/referrer/permissions hardening
    "csp": 0.20,            # XSS's primary browser-enforced defense
    "hsts": 0.08,
    "mixed_content": 0.07,
}

_OTHER_CATEGORY = "other"
_OTHER_WEIGHT = 0.05


@dataclass
class SecurityScoreResult:
    overall: int
    breakdown: Dict[str, int] = field(default_factory=dict)
    counts_by_severity: Dict[str, int] = field(default_factory=dict)
    findings: List[dict] = field(default_factory=list)


def score_security(findings: List[dict], ssl_checked: bool = True) -> SecurityScoreResult:
    """Scores security findings. ssl_checked=False drops the SSL category (http URL; already covered by HTTPS)."""
    by_category: Dict[str, List[dict]] = {}
    for finding in findings:
        category = finding.get("category") or _OTHER_CATEGORY
        by_category.setdefault(category, []).append(finding)

    weights = dict(CATEGORY_WEIGHTS)
    if not ssl_checked:
        weights.pop("ssl", None)

    breakdown: Dict[str, int] = {}
    weight_total = 0.0
    weighted_sum = 0.0

    all_categories = set(weights) | set(by_category)
    if not ssl_checked:
        all_categories.discard("ssl")

    for category in all_categories:
        weight = weights.get(category, _OTHER_WEIGHT)
        score = _score_category(by_category.get(category, []))
        breakdown[category] = score
        weight_total += weight
        weighted_sum += score * weight

    overall = round(weighted_sum / weight_total) if weight_total else 100

    counts_by_severity: Dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
    for finding in findings:
        severity = finding.get("severity", "info")
        counts_by_severity[severity] = counts_by_severity.get(severity, 0) + 1

    return SecurityScoreResult(
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
