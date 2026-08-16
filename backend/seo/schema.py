"""
seo/schema.py

Page-level structured-data (schema.org JSON-LD) checks: whether any
structured data is present at all, whether declared blocks are
malformed, and whether each parsed block has the minimum shape (@context
pointing at schema.org, an @type) search engines require to build rich
results from it.

crawler.parser already parses every <script type="application/ld+json">
block and silently drops ones that fail json.loads — that's the right
behavior for the crawler (one bad block shouldn't break page parsing),
but it means a malformed-block *count* isn't visible on ParsedPage. This
module re-scans page.soup to recover that count for the "malformed"
finding; everything else works off the already-parsed page.json_ld list.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from crawler.parser import ParsedPage

MODULE = "seo"
CATEGORY = "schema"

def check_structured_data(page: ParsedPage) -> List[dict]:
    """Findings for one page's JSON-LD structured data."""
    findings: List[dict] = []

    raw_blocks = page.soup.find_all("script", attrs={"type": "application/ld+json"})
    malformed_count = _count_malformed(raw_blocks)

    if malformed_count:
        findings.append(_finding(
            "warning",
            "Malformed structured data",
            f"{page.url} has {malformed_count} <script type=\"application/ld+json\"> block(s) "
            "that fail to parse as JSON, so search engines will ignore them entirely.",
            recommendation="Validate JSON-LD blocks (e.g. with Google's Rich Results Test) "
                            "and fix the JSON syntax.",
        ))

    if not page.json_ld:
        if not malformed_count:
            findings.append(_finding(
                "info",
                "No structured data found",
                f"{page.url} has no JSON-LD structured data. Structured data doesn't "
                "guarantee rich results, but it's how search engines identify eligible "
                "content for them.",
                recommendation="Add JSON-LD structured data relevant to the page (e.g. "
                                "Organization, Article, Product, or BreadcrumbList).",
            ))
        return findings

    for block in page.json_ld:
        findings += _check_block(page.url, block)

    return findings


def _check_block(url: str, block: Any) -> List[dict]:
    findings: List[dict] = []
    entries = block if isinstance(block, list) else [block]

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        context = str(entry.get("@context", ""))
        schema_type = entry.get("@type")

        if "schema.org" not in context:
            findings.append(_finding(
                "info",
                "Structured data missing schema.org context",
                f"A JSON-LD block on {url} has @context = \"{context or 'missing'}\" instead "
                "of https://schema.org, so it may not be recognized as schema.org markup.",
                recommendation="Set @context to \"https://schema.org\" on every JSON-LD block.",
            ))

        if not schema_type:
            findings.append(_finding(
                "warning",
                "Structured data missing @type",
                f"A JSON-LD block on {url} has no @type, so search engines can't tell what "
                "kind of entity it describes.",
                recommendation="Add an @type (e.g. \"Organization\", \"Product\", \"Article\") "
                                "to every JSON-LD block.",
            ))

    return findings


def _count_malformed(raw_blocks: List[Any]) -> int:
    malformed = 0
    for tag in raw_blocks:
        raw = tag.string or tag.get_text()
        if not raw or not raw.strip():
            continue
        try:
            json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            malformed += 1
    return malformed


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
