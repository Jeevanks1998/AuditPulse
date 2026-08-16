"""
security/security_score.py

Turns the flat finding lists every other security/ module returns into
a single weighted 0-100 score with a per-category breakdown — same
shape as accessibility/accessibility_score.py and
performance/performance_score.py, so this drops straight into
services.audit_service in place of the
`breakdown["security"] = random.randint(80, 99)` placeholder.

Scoring model: every category starts at 100 and loses points per
finding by severity, then categories are combined by weight. SSL and
HTTPS get the largest weights since a failure there (expired cert, no
TLS at all) undermines every other control — a perfect CSP on a site
serving plain HTTP is not "mostly secure". A category with no findings
scores 100, same reasoning as accessibility_score.py: absence of
findings in an *available* category is a real signal (nothing wrong
was found), it's only ssl.py's `checked=False` case (non-https URL)
that should be excluded from scoring entirely rather than counted as a
clean pass — see `score_security`'s `ssl_checked` parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

MODULE = "security"

SEVERITY_PENALTY = {"critical": 30, "warning": 12, "info": 3}

# Must sum to 1.0 (before any renormalization when ssl is excluded).
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
    """
    Scores a flat list of finding dicts (as returned by security.https,
    security.ssl, security.headers, security.hsts, security.csp,
    security.mixed_content, concatenated for one audited URL) into an
    overall score plus per-category breakdown.

    Pass `ssl_checked=False` when security.ssl.check_ssl returned an
    unchecked SslInfo (i.e. the URL wasn't https at all, so no
    handshake was attempted) — the ssl category is dropped from
    scoring entirely rather than counted as a clean 100, since the
    https category's own "not served over HTTPS" finding already
    covers that failure without double-counting it as two separate
    perfect/failing categories.
    """
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
