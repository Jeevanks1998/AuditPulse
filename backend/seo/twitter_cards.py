"""
seo/twitter_cards.py

Page-level Twitter/X Card checks: card type validity and whether the
supporting title/description/image tags are present. X will fall back
to a page's Open Graph tags for a lot of this, so the checks here are
mostly `info` severity — a gap here isn't as consequential as a missing
og:* tag, just a smaller miss.
"""

from __future__ import annotations

from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "seo"
CATEGORY = "twitter_cards"

VALID_CARD_TYPES = {"summary", "summary_large_image", "app", "player"}


def check_twitter_cards(page: ParsedPage) -> List[dict]:
    """Findings for one page's twitter:* meta tags."""
    meta = page.meta or {}
    card = (meta.get("twitter:card") or "").strip().lower()

    if not card:
        has_og = any((meta.get(tag) or "").strip() for tag in ("og:title", "og:description", "og:image"))
        return [_finding(
            "info",
            "No Twitter Card tag found",
            f"{page.url} has no twitter:card meta tag."
            + (" X will fall back to Open Graph tags where present, so the impact is small."
               if has_og else " With no Open Graph tags either, shared links will show no "
               "card at all."),
            recommendation="Add twitter:card (usually \"summary_large_image\") plus "
                            "twitter:title, twitter:description, and twitter:image.",
        )]

    findings: List[dict] = []
    if card not in VALID_CARD_TYPES:
        findings.append(_finding(
            "warning",
            "Invalid Twitter Card type",
            f"twitter:card on {page.url} is \"{card}\", which isn't one of the recognized "
            f"types ({', '.join(sorted(VALID_CARD_TYPES))}).",
            recommendation="Use one of: " + ", ".join(sorted(VALID_CARD_TYPES)) + ".",
        ))

    required = ("twitter:title", "twitter:description")
    if card == "summary_large_image" or card == "summary":
        required = required + ("twitter:image",)

    missing = [tag for tag in required if not (meta.get(tag) or "").strip()]
    if missing:
        findings.append(_finding(
            "info",
            "Incomplete Twitter Card tags",
            f"{page.url} declares twitter:card=\"{card}\" but is missing: {', '.join(missing)}.",
            recommendation=f"Add the missing tag(s): {', '.join(missing)}.",
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
