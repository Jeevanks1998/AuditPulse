"""
ai/priority.py

Ranks a completed audit's findings into a single fix-first order, feeding
reports/generator.py's `priorities` field and action_plan.py's grouping.
Unlike executive_summary.py / recommendations.py / business_impact.py,
this is intentionally rule-based rather than AI-generated: ranking is a
sort, not prose, and a sort should be reproducible — running the same
audit twice should never reshuffle what "fix this first" means.

Score model: severity is the dominant signal (a critical is always ranked
above a warning, which is always ranked above an info), with the parent
module's breakdown score as a tiebreaker within a severity band — a
finding from a module scoring 40/100 is a stronger signal of a systemic
problem than the same-severity finding from a module scoring 85/100, so
it sorts first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}

# Rough, deterministic effort estimate by severity — used to label each
# prioritized item and to group action_plan.py's quick-wins vs long-term
# buckets. Not a substitute for real estimation, just a consistent default.
EFFORT_BY_SEVERITY = {"critical": "high", "warning": "medium", "info": "low"}


@dataclass
class PrioritizedFinding:
    rank: int
    module: str
    severity: str
    title: str
    description: str
    recommendation: str = ""
    effort: str = "medium"


def prioritize_findings(findings: List[dict], breakdown: Dict[str, int]) -> List[PrioritizedFinding]:
    """
    Returns `findings` sorted fix-first: severity first, then the parent
    module's breakdown score ascending (weaker modules sort earlier), then
    original order as a stable final tiebreaker.
    """
    if not findings:
        return []

    indexed = list(enumerate(findings))

    def sort_key(pair):
        index, finding = pair
        severity = finding.get("severity", "info")
        module_score = breakdown.get(finding.get("module", ""), 50)
        return (SEVERITY_RANK.get(severity, 3), module_score, index)

    ordered = sorted(indexed, key=sort_key)

    prioritized: List[PrioritizedFinding] = []
    for rank, (_, finding) in enumerate(ordered, start=1):
        severity = finding.get("severity", "info")
        prioritized.append(
            PrioritizedFinding(
                rank=rank,
                module=finding.get("module", "general"),
                severity=severity,
                title=finding.get("title", ""),
                description=finding.get("description", ""),
                recommendation=finding.get("recommendation") or "",
                effort=EFFORT_BY_SEVERITY.get(severity, "medium"),
            )
        )
    return prioritized


def top_priorities(findings: List[dict], breakdown: Dict[str, int], limit: int = 5) -> List[PrioritizedFinding]:
    """Convenience wrapper for callers (reports/generator.py) that only need the head of the list."""
    return prioritize_findings(findings, breakdown)[:limit]
