"""
ux/spacing.py

A static, best-effort look at whether clickable elements are crowded
together. True rendered spacing needs a real layout engine — this
module can't see computed margins from an external stylesheet — so it
looks for two proxies that don't require rendering:

  1. Runs of adjacent, unseparated inline links/buttons — several
     <a>/<button> elements sitting back-to-back with no whitespace or
     separating element between them, a common source of accidental
     mis-taps on touch devices.
  2. Explicit zero-margin declarations on interactive elements, which
     is the one spacing signal that *is* visible without rendering
     (inline style / <style> block, same declared-only scope as
     ux/typography.py and ux/colors.py).

Both are heuristics that flag likely problems, not a substitute for
an actual rendered-layout tap-target audit (which is what
accessibility/axe.py's Lighthouse pass covers via its own tap-target
audit).
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "ux"
CATEGORY = "spacing"

INTERACTIVE_TAGS = ("a", "button")
MIN_RUN_LENGTH = 4      # this many unseparated interactive siblings in a row is worth flagging
MAX_EXAMPLES = 3

_DECL_RE = re.compile(r"([\w-]+)\s*:\s*([^;]+)")
_ZERO_RE = re.compile(r"^0(px|em|rem|%)?$")


def check_spacing(page: ParsedPage) -> List[dict]:
    """Findings for crowded runs of interactive elements and explicit zero-margin buttons/links."""
    findings: List[dict] = []
    findings += _check_unseparated_runs(page)
    findings += _check_zero_margin_interactive(page)
    return findings


def _check_unseparated_runs(page: ParsedPage) -> List[dict]:
    runs = []
    for parent in page.soup.find_all(True):
        run = []
        for child in parent.find_all(recursive=False):
            if child.name in INTERACTIVE_TAGS:
                run.append(child)
            else:
                if len(run) >= MIN_RUN_LENGTH:
                    runs.append(run)
                run = []
        if len(run) >= MIN_RUN_LENGTH:
            runs.append(run)

    # only count runs where consecutive elements have no separating whitespace
    # text between them in the source, since that's the closest static signal
    # to "these will render touching each other"
    crowded_runs = [run for run in runs if _no_separating_text(run)]
    if not crowded_runs:
        return []

    longest = max(crowded_runs, key=len)
    labels = [
        (tag.get_text(strip=True) or tag.name) for tag in longest[:MAX_EXAMPLES]
    ]
    return [_finding(
        "info",
        "Interactive elements packed together with no spacing markup",
        f"{page.url} has a run of {len(longest)} links/buttons in a row "
        f"(e.g. {', '.join(labels)}, ...) with no whitespace or separating element between "
        "them in the markup. Without CSS spacing explicitly compensating, tightly packed "
        "tap targets are a common source of accidental mis-taps, especially on touch "
        "devices.",
        recommendation="Add visible spacing (margin/gap) between adjacent interactive "
                        "elements — a `gap` on a flex/grid container is the simplest fix — "
                        "and confirm on an actual mobile viewport that targets don't touch.",
    )]


def _no_separating_text(run) -> bool:
    for i in range(len(run) - 1):
        between = run[i].next_sibling
        # walk siblings between run[i] and run[i+1]; any non-whitespace text breaks the run
        while between is not None and between is not run[i + 1]:
            if getattr(between, "strip", None) and between.strip():
                return False
            between = getattr(between, "next_sibling", None)
    return True


def _check_zero_margin_interactive(page: ParsedPage) -> List[dict]:
    zero_margin_count = 0
    for tag_name in INTERACTIVE_TAGS:
        for tag in page.soup.find_all(tag_name, style=True):
            decls = dict(_DECL_RE.findall(tag.get("style", "")))
            margin = decls.get("margin", "").strip().lower()
            if margin and _ZERO_RE.match(margin):
                zero_margin_count += 1

    if zero_margin_count < MIN_RUN_LENGTH:
        return []

    return [_finding(
        "info",
        "Interactive elements with explicit zero margin",
        f"{page.url} has {zero_margin_count} link(s)/button(s) with an inline `margin: 0` "
        "declaration. Explicitly zeroing margin on clickable elements is sometimes "
        "intentional (e.g. inside a flex container using `gap` instead), but worth "
        "confirming these don't end up touching neighboring tap targets.",
        recommendation="If spacing is meant to come from a parent `gap`, confirm the "
                        "parent is actually a flex/grid container; otherwise replace the "
                        "zeroed margin with real spacing.",
    )]


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
