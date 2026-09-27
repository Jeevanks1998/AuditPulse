"""
cookies/expiry.py

Turns a cookie's raw Max-Age/Expires attributes into a lifetime
classification (session vs. short/medium/long-lived persistent) and
flags retention that's excessive for its category — e.g. a marketing
cookie set to live for two years is a common GDPR/ePrivacy finding
("cookies should be kept no longer than necessary for their purpose").

Deliberately independent of cookies.detector.Cookie so it can be unit
tested against plain (days, category) pairs without constructing a
full Cookie object first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from cookies.categories import ANALYTICS, ESSENTIAL, FUNCTIONAL, MARKETING

SESSION = "session"
SHORT = "short"        # <= 1 day
MEDIUM = "medium"       # <= 90 days
LONG = "long"          # <= 365 days
EXCESSIVE = "excessive"  # > 365 days

# CNIL/ICO guidance benchmarks: 13 months (~395 days) is the commonly
# cited upper bound for analytics cookies; marketing/ad cookies are
# routinely flagged well before that. These are heuristics, not law.
_CATEGORY_MAX_DAYS = {
    ESSENTIAL: None,     # no cap — session lifetime is the vendor's call
    FUNCTIONAL: 365,
    ANALYTICS: 395,
    MARKETING: 90,
}
_DEFAULT_MAX_DAYS = 365


@dataclass
class ExpiryClassification:
    lifetime_bucket: str          # SESSION | SHORT | MEDIUM | LONG | EXCESSIVE
    lifetime_days: Optional[float]  # None for session cookies
    exceeds_category_guidance: bool


def classify_expiry(max_age_seconds: Optional[float], category: str) -> ExpiryClassification:
    """
    `max_age_seconds` is None for a session cookie (no Max-Age/Expires
    attribute at all — browser drops it when the session ends).
    """
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
    """Human-readable one-liner used in finding descriptions."""
    if classification.lifetime_bucket == SESSION:
        return "expires when the browser session ends"
    days = classification.lifetime_days or 0
    if days < 1:
        return f"expires in under a day ({round(days * 24)}h)"
    return f"expires in ~{int(days)} day(s)"
