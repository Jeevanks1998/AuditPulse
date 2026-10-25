"""
Ranks findings in fix-first order (rule-based, so it is the same every run).

Severity comes first; within a severity, findings from the weaker module
come first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}

# Rough effort label per severity; also drives action_plan.py's groups.
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
    """Sorts findings fix-first: severity, then weaker module first, then original order."""
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
    """First `limit` items of prioritize_findings()."""
    return prioritize_findings(findings, breakdown)[:limit]
