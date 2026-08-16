"""
cookies/categories.py

Classifies a single cookie name (optionally with its domain) into one
of the buckets a consent banner is supposed to let a visitor opt in/out
of independently: "essential", "functional", "analytics", "marketing",
or "unknown" when nothing in the lookup table recognizes it.

This is a lookup-table + pattern approach rather than anything that
tries to infer intent from cookie *values* — matches how every other
static detector in this codebase (analytics/*, seo/*) works: known
signatures in, a category out, no live behavioral analysis required.
The table is intentionally small and well-known-vendor-focused; an
unrecognized cookie is left as "unknown" rather than guessed at, since
a wrong guess here (e.g. calling a marketing cookie "essential") is
worse than admitting we don't know.
"""

from __future__ import annotations

import re
from typing import Optional

ESSENTIAL = "essential"
FUNCTIONAL = "functional"
ANALYTICS = "analytics"
MARKETING = "marketing"
UNKNOWN = "unknown"

CATEGORIES = (ESSENTIAL, FUNCTIONAL, ANALYTICS, MARKETING, UNKNOWN)

# Exact-name matches first (cheapest, least ambiguous). Vendor prefixes
# handled separately below via _PREFIX_RULES for families like _ga_XXXX.
_EXACT_NAME_RULES = {
    # --- essential / strictly-necessary ---
    "session": ESSENTIAL,
    "sessionid": ESSENTIAL,
    "phpsessid": ESSENTIAL,
    "jsessionid": ESSENTIAL,
    "asp.net_sessionid": ESSENTIAL,
    "csrftoken": ESSENTIAL,
    "xsrf-token": ESSENTIAL,
    "cf_clearance": ESSENTIAL,
    "__cf_bm": ESSENTIAL,
    "cookieconsent_status": ESSENTIAL,
    "cookie_consent": ESSENTIAL,
    "onetrust-consent": ESSENTIAL,  # matched loosely below too (OptanonConsent etc.)

    # --- functional / preferences ---
    "lang": FUNCTIONAL,
    "language": FUNCTIONAL,
    "currency": FUNCTIONAL,
    "timezone": FUNCTIONAL,
    "theme": FUNCTIONAL,

    # --- analytics ---
    "_ga": ANALYTICS,
    "_gid": ANALYTICS,
    "_gat": ANALYTICS,
    "_hjsessionuser": ANALYTICS,
    "_hjsession": ANALYTICS,
    "_hjincludedinsessionsample": ANALYTICS,
    "_clck": ANALYTICS,
    "_clsk": ANALYTICS,
    "amplitude_id": ANALYTICS,
    "mp_mixpanel": ANALYTICS,

    # --- marketing / advertising ---
    "_fbp": MARKETING,
    "_fbc": MARKETING,
    "fr": MARKETING,
    "ide": MARKETING,
    "muid": MARKETING,
    "_ttp": MARKETING,
    "_uetsid": MARKETING,
    "_uetvid": MARKETING,
    "nid": MARKETING,
    "personalization_id": MARKETING,
    "li_sugr": MARKETING,
    "bcookie": MARKETING,
    "bscookie": MARKETING,
    "lidc": MARKETING,
}

# (regex, category) pairs, checked in order, for names with variable
# suffixes (GA4's per-property `_ga_<CONTAINER_ID>` being the classic
# case) or vendor cookies whose exact spelling varies by CMP/version.
_PREFIX_RULES = [
    (re.compile(r"^_ga_[A-Z0-9]+$"), ANALYTICS),
    (re.compile(r"^_gcl_", re.IGNORECASE), MARKETING),          # Google Ads click-id cookies
    (re.compile(r"^_gads$", re.IGNORECASE), MARKETING),
    (re.compile(r"^optanonconsent$", re.IGNORECASE), ESSENTIAL),  # OneTrust
    (re.compile(r"^optanonalertboxclosed$", re.IGNORECASE), ESSENTIAL),
    (re.compile(r"^cookieyes-", re.IGNORECASE), ESSENTIAL),
    (re.compile(r"^cookielawinfo-", re.IGNORECASE), ESSENTIAL),  # CookieYes / CookieLaw
    (re.compile(r"^__hs", re.IGNORECASE), MARKETING),            # HubSpot
    (re.compile(r"^hubspotutk$", re.IGNORECASE), MARKETING),
    (re.compile(r"^__hstc$", re.IGNORECASE), ANALYTICS),
    (re.compile(r"^_pin_unauth$", re.IGNORECASE), MARKETING),    # Pinterest
    (re.compile(r"^_scid$", re.IGNORECASE), ANALYTICS),          # Snapchat
    (re.compile(r"^__stripe_", re.IGNORECASE), ESSENTIAL),       # Stripe fraud/session
    (re.compile(r"^wordpress_logged_in", re.IGNORECASE), ESSENTIAL),
    (re.compile(r"^wp-settings", re.IGNORECASE), FUNCTIONAL),
]

# Domains whose cookies are near-certainly one category regardless of
# the exact cookie name — used as a fallback when the name itself
# doesn't match anything above (e.g. a vendor's less-common cookie).
_DOMAIN_HINTS = [
    (re.compile(r"(^|\.)doubleclick\.net$", re.IGNORECASE), MARKETING),
    (re.compile(r"(^|\.)googlesyndication\.com$", re.IGNORECASE), MARKETING),
    (re.compile(r"(^|\.)googleadservices\.com$", re.IGNORECASE), MARKETING),
    (re.compile(r"(^|\.)facebook\.com$", re.IGNORECASE), MARKETING),
    (re.compile(r"(^|\.)ads-twitter\.com$", re.IGNORECASE), MARKETING),
    (re.compile(r"(^|\.)google-analytics\.com$", re.IGNORECASE), ANALYTICS),
    (re.compile(r"(^|\.)analytics\.google\.com$", re.IGNORECASE), ANALYTICS),
    (re.compile(r"(^|\.)hotjar\.com$", re.IGNORECASE), ANALYTICS),
    (re.compile(r"(^|\.)clarity\.ms$", re.IGNORECASE), ANALYTICS),
]

DISPLAY_NAMES = {
    ESSENTIAL: "Strictly necessary",
    FUNCTIONAL: "Functional",
    ANALYTICS: "Analytics",
    MARKETING: "Marketing / advertising",
    UNKNOWN: "Unknown",
}


def categorize_cookie(name: str, domain: Optional[str] = None) -> str:
    """
    Best-effort classification of one cookie. Order of precedence:
    exact name match, prefix/regex match, domain hint, then "unknown".
    Matching is case-insensitive on the name since real-world cookie
    names vary in casing across vendors/versions.
    """
    key = (name or "").strip().lower()
    if not key:
        return UNKNOWN

    if key in _EXACT_NAME_RULES:
        return _EXACT_NAME_RULES[key]

    for pattern, category in _PREFIX_RULES:
        if pattern.search(key):
            return category

    if domain:
        for pattern, category in _DOMAIN_HINTS:
            if pattern.search(domain.strip().lower()):
                return category

    return UNKNOWN


def display_name(category: str) -> str:
    return DISPLAY_NAMES.get(category, category.title())
