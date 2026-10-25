"""
Classifies a cookie's lifetime (session, short, medium, long, excessive) and
flags lifetimes too long for its category (e.g. a 2-year marketing cookie).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from cookies.categories import ANALYTICS, CONSENT_MANAGEMENT, ESSENTIAL, FUNCTIONAL, MARKETING

SESSION = "session"
SHORT = "short"        # <= 1 day
MEDIUM = "medium"       # <= 90 days
LONG = "long"          # <= 365 days
EXCESSIVE = "excessive"  # > 365 days

# Guidance (CNIL/ICO): about 13 months for analytics, less for marketing. Rules of thumb, not law.
_CATEGORY_MAX_DAYS = {
    ESSENTIAL: None,     # no limit
    FUNCTIONAL: 365,
    ANALYTICS: 395,
    MARKETING: 90,
    # CNIL: ask for consent again after about 13 months.
    CONSENT_MANAGEMENT: 395,
}
_DEFAULT_MAX_DAYS = 365


@dataclass
class ExpiryClassification:
    lifetime_bucket: str          # SESSION | SHORT | MEDIUM | LONG | EXCESSIVE
    lifetime_days: Optional[float]  # None for session cookies
    exceeds_category_guidance: bool


def classify_expiry(max_age_seconds: Optional[float], category: str) -> ExpiryClassification:
    """`max_age_seconds` is None for a session cookie."""
    if max_age_seconds is None:
        return ExpiryClassification(SESSION, None, exceeds_category_guidance=False)

    days = max(0.0, max_age_seconds) / 86400
    bucket = _bucket_for(days)
    cap = _CATEGORY_MAX_DAYS.get(category, _DEFAULT_MAX_DAYS)
    exceeds = cap is not None and days > cap

    return ExpiryClassification(bucket, round(days, 2), exceeds_category_guidance=exceeds)


def _bucket_for(days: float) -> str:
    if days <= 1:
        return SHORT
    if days <= 90:
        return MEDIUM
    if days <= 365:
        return LONG
    return EXCESSIVE


def describe_lifetime(classification: ExpiryClassification) -> str:
    """One-line description for findings."""
    if classification.lifetime_bucket == SESSION:
        return "expires when the browser session ends"
    days = classification.lifetime_days or 0
    if days < 1:
        return f"expires in under a day ({round(days * 24)}h)"
    return f"expires in ~{int(days)} day(s)"
