"""
pdf/issues.py

Turns the raw findings list into a short list of *issues to fix*.

The raw list repeats itself a lot — e.g. "Google Tag Manager loaded more
than once" once per scanned page (43 rows on a big site), or "Conversion
interaction not tracked: <file>" once per PDF link. Here those become one
issue each, with the affected pages/items listed underneath, so a reader
sees ~15 things to fix instead of 70 rows.

The report's "Start here" page lists the most urgent of these; the
appendix lists every place each of them was found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pdf.components import short_url

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}

# Modules whose findings are commentary rather than something to fix.
_SKIP_MODULES = {"ai"}

# Plain-language "why it matters", most specific match first.
_WHY_BY_TITLE = [
    (r"broken important cta|broken .*link|did not work|404", "Visitors click this and nothing useful happens, so you lose leads and trust."),
    (r"not tracked|no analytics detected|tracking gap|no analytics event", "These actions happen on your site but never reach analytics, so conversions are under-reported."),
    (r"tracking inconsistency", "Similar buttons are measured differently, which makes reports hard to compare and trust."),
    (r"difficult to verify", "We couldn't see a clear result after clicking, so a visitor may not either."),
    (r"before consent|not held back|without consent", "Collecting data before a visitor agrees breaks GDPR/ePrivacy rules and can lead to fines."),
    (r"change cookie preferences|withdraw", "Visitors must be able to change their mind about cookies at any time; regulators check this."),
    (r"no cookie-consent banner|no consent banner|banner", "Without a working consent banner, non-essential cookies have no legal basis in many regions."),
    (r"loaded more than once|duplicate", "The same visit is counted more than once, inflating numbers and skewing every report."),
    (r"missing from some pages|missing on", "Pages without the tag are invisible in analytics, leaving gaps in your data."),
    (r"scroll|click", "Engagement isn't measured, so you can't tell which content works."),
]
_WHY_BY_MODULE = {
    "consent": "Consent problems carry legal risk (GDPR / ePrivacy / CCPA) and damage visitor trust.",
    "analytics": "Tracking problems mean decisions are made on incomplete or wrong numbers.",
    "journey": "Problems in key journeys cost leads and hide what visitors really do.",
}

_URL_RE = re.compile(r"https?://[^\s\"'“”<>)]+")


@dataclass
class Issue:
    module: str
    severity: str
    title: str
    description: str
    recommendation: str
    items: List[str] = field(default_factory=list)
    count: int = 1

    @property
    def why(self) -> str:
        low = (self.title + " " + self.description).lower()
        for pattern, text in _WHY_BY_TITLE:
            if re.search(pattern, low):
                return text
        return _WHY_BY_MODULE.get(self.module, "Fixing this improves the reliability of your site and its data.")


def _split_title(title: str):
    """'Conversion interaction not tracked: Go to slide 2' -> ('Conversion
    interaction not tracked', 'Go to slide 2'). Titles without a
    'Prefix: subject' shape come back unchanged with no subject."""
    if ":" in title:
        head, tail = title.split(":", 1)
        if len(head.split()) >= 2 and tail.strip() and not head.lower().startswith("http"):
            return head.strip(), tail.strip()
    return title.strip(), None


def _item_for(finding: dict, subject: Optional[str]) -> Optional[str]:
    urls = list(dict.fromkeys(m.rstrip(".,;") for m in _URL_RE.findall(finding.get("description") or "")))
    if subject:
        label = short_url(subject) if subject.startswith("http") else subject
        page = next((u for u in urls if u != subject), None)
        if page:
            return f"{label} — on {short_url(page)}"
        return label
    for u in finding.get("affected_urls") or []:
        return short_url(u)
    if urls:
        return short_url(urls[0])
    return None


def group_findings(findings: List[dict], module_scores: Optional[Dict[str, int]] = None) -> List[Issue]:
    module_scores = module_scores or {}
    groups: Dict[tuple, Issue] = {}
    for f in findings or []:
        module = (f.get("module") or "other").lower()
        if module in _SKIP_MODULES:
            continue
        severity = (f.get("severity") or "info").lower()
        if severity not in SEVERITY_ORDER:
            severity = "info"
        head, subject = _split_title(f.get("title") or "Finding")
        key = (module, severity, head.lower())
        item = _item_for(f, subject)
        issue = groups.get(key)
        if issue is None:
            issue = Issue(
                module=module, severity=severity, title=head,
                description=(f.get("description") or "").strip(),
                recommendation=(f.get("recommendation") or "").strip(),
                count=0,
            )
            groups[key] = issue
            issue._subject_titled = bool(subject)  # type: ignore[attr-defined]
        issue.count += 1
        if item and item not in issue.items:
            issue.items.append(item)
        if not issue.recommendation and f.get("recommendation"):
            issue.recommendation = f["recommendation"].strip()
    issues = list(groups.values())
    for i in issues:
        # A single "Prefix: subject" finding keeps its full, specific title.
        if i.count == 1 and getattr(i, "_subject_titled", False) and i.items:
            pass
    issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], module_scores.get(i.module, 100), -i.count, i.title))
    return issues


def issue_counts(issues: List[Issue]) -> Dict[str, int]:
    out = {"critical": 0, "warning": 0, "info": 0}
    for i in issues:
        out[i.severity] += 1
    return out
