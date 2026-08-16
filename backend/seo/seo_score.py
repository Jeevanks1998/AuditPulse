"""
seo/seo_score.py

Turns the flat finding lists every other seo/ module returns into a
single weighted 0-100 score with a per-category breakdown — the same
shape Audit.breakdown["seo"] and AuditStatsOut.breakdown already carry,
so this can drop straight into services.audit_service in place of the
`breakdown["seo"] = random.randint(75, 98)` placeholder.

Scoring model: every category (title, meta, headings, canonical,
schema, open_graph, twitter_cards, images, sitemap, robots, links)
starts at 100 and loses points per finding by severity. Categories with
no findings at all stay at 100 rather than being penalized for absence
of data. The overall score is the weighted average of category scores,
using CATEGORY_WEIGHTS so on-page fundamentals (title, meta, headings)
count for more than lower-stakes social-card niceties.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

MODULE = "seo"

SEVERITY_PENALTY = {"critical": 25, "warning": 12, "info": 4}

# Must sum to 1.0. Categories not listed here (e.g. an unrecognized
# `category` value on a finding) are folded into "other" at a small
# default weight so nothing is silently dropped from the overall score.
CATEGORY_WEIGHTS: Dict[str, float] = {
    "title": 0.16,
    "meta": 0.12,
    "headings": 0.12,
    "canonical": 0.10,
    "schema": 0.08,
    "open_graph": 0.07,
    "twitter_cards": 0.05,
    "images": 0.12,
    "sitemap": 0.10,
    "robots": 0.10,
    "links": 0.08,
}

_OTHER_CATEGORY = "other"
_OTHER_WEIGHT = 0.05


@dataclass
class SEOScoreResult:
    overall: int
    breakdown: Dict[str, int] = field(default_factory=dict)
    counts_by_severity: Dict[str, int] = field(default_factory=dict)
    findings: List[dict] = field(default_factory=list)


def score_seo(findings: List[dict]) -> SEOScoreResult:
    """
    Scores a flat list of finding dicts (as returned by seo.run_page_checks
    / seo.run_site_checks, or concatenated across an entire crawl) into
    an overall score plus per-category breakdown.
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

    return SEOScoreResult(
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
