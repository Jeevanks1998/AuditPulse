"""
seo/title.py

Page-level <title> checks: presence, length, and generic/placeholder
text, plus a site-level helper for spotting titles duplicated across
more than one crawled page. Operates on crawler.parser.ParsedPage so it
slots in anywhere a ParsedPage already exists (crawler.crawler, tests,
a notebook) with no re-parsing of HTML.

Every check function here returns a list of finding dicts shaped like
{module, category, severity, title, description, recommendation} — the
same fields services.audit_service / models.issue already read, plus
an extra `category` key seo_score.py uses to bucket the per-category
breakdown (harmless to any consumer that only reads the original keys).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from crawler.parser import ParsedPage

MODULE = "seo"
CATEGORY = "title"

TITLE_MIN_LEN = 30
TITLE_MAX_LEN = 60

_PLACEHOLDER_TITLES = {
    "untitled", "untitled document", "untitled page", "home", "new page",
    "index", "document", "index.html", "welcome", "welcome to nginx!",
}


def check_title(page: ParsedPage) -> List[dict]:
    """Findings for a single page's <title>: missing, mis-sized, or a CMS/server default."""
    findings: List[dict] = []
    title = (page.title or "").strip()

    if not title:
        findings.append(_finding(
            "critical",
            "Missing <title> tag",
            f"{page.url} has no <title> tag, or it is empty. Search engines fall back to "
            "the URL or an auto-generated snippet, which hurts click-through from results "
            "pages and gives the browser tab/bookmark no useful label.",
            recommendation=f"Add a unique, descriptive <title> between {TITLE_MIN_LEN} and "
                            f"{TITLE_MAX_LEN} characters.",
        ))
        return findings

    length = len(title)
    if length < TITLE_MIN_LEN:
        findings.append(_finding(
            "info",
            "Title tag is short",
            f"The title on {page.url} is {length} characters (\"{title}\"). Titles under "
            f"{TITLE_MIN_LEN} characters often leave search-result real estate unused.",
            recommendation=f"Expand toward {TITLE_MIN_LEN}-{TITLE_MAX_LEN} characters, leading "
                            "with the page's primary keyword and a clear value proposition.",
        ))
    elif length > TITLE_MAX_LEN:
        findings.append(_finding(
            "warning",
            "Title tag is too long",
            f"The title on {page.url} is {length} characters. Search engines typically "
            f"truncate titles past roughly {TITLE_MAX_LEN} characters in results.",
            recommendation=f"Shorten to {TITLE_MIN_LEN}-{TITLE_MAX_LEN} characters, keeping the "
                            "most important terms first so truncation doesn't cut them off.",
        ))

    if title.strip().lower() in _PLACEHOLDER_TITLES:
        findings.append(_finding(
            "warning",
            "Title looks like a placeholder",
            f"The title on {page.url} (\"{title}\") matches a common CMS or server default "
            "rather than page-specific copy.",
            recommendation="Replace the default title with unique, page-specific copy.",
        ))

    return findings


def check_duplicate_titles(page_titles: Dict[str, Optional[str]]) -> List[dict]:
    """
    Site-level check across a crawl. `page_titles` maps url -> title text
    (e.g. {p.url: p.title for p in crawl_result.ok_pages}). Flags any
    title shared by more than one URL, since duplicate titles make it
    hard for search engines — and users scanning results — to tell
    pages apart.
    """
    by_title: Dict[str, List[str]] = defaultdict(list)
    for url, title in page_titles.items():
        normalized = (title or "").strip().lower()
        if normalized:
            by_title[normalized].append(url)

    findings: List[dict] = []
    for normalized, urls in by_title.items():
        if len(urls) > 1:
            shown = ", ".join(urls[:5])
            extra = f" and {len(urls) - 5} more" if len(urls) > 5 else ""
            findings.append(_finding(
                "warning",
                "Duplicate title tag across pages",
                f"{len(urls)} pages share the same title: {shown}{extra}.",
                recommendation="Give each page a unique title that reflects its own content.",
            ))
    return findings


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
