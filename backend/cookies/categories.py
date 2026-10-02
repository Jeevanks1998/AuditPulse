"""
cookies/categories.py

Central cookie classifier. Classifies a single cookie name (optionally
with its domain) into one of the buckets a consent banner is supposed to
let a visitor opt in/out of independently:

    essential           — strictly necessary: sessions, CSRF/XSRF tokens,
                          load balancing, bot/fraud protection
    functional          — preferences the visitor asked for (language,
                          currency, theme)
    analytics           — measurement / audience statistics
    marketing           — advertising, retargeting, social pixels
    consent_management  — the CMP's own storage of the visitor's choice
                          (OptanonConsent, CookieConsent, euconsent-v2…)
    unknown             — nothing in the lookup tables recognized it

`consent_management` is deliberately its own bucket rather than being
folded into "essential": a report should be able to say
"OptanonConsent — Consent Management" rather than
"OptanonConsent — Strictly Necessary", and a CMP storing the visitor's
choice is never evidence of a consent failure.

`unknown` stays `unknown`. An unrecognized cookie is *not* treated as
non-essential automatically — a wrong guess here (calling a session
cookie "marketing", or a marketing cookie "essential") is worse than
admitting we don't know. Callers that need a yes/no answer should use
`requires_consent()` (True only for analytics/marketing) and report
unknown cookies separately as "needs review" evidence.

Lookup-table + pattern approach, no inference from cookie *values* —
same as every other static detector in this codebase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

ESSENTIAL = "essential"
FUNCTIONAL = "functional"
ANALYTICS = "analytics"
MARKETING = "marketing"
CONSENT_MANAGEMENT = "consent_management"
UNKNOWN = "unknown"

CATEGORIES = (ESSENTIAL, FUNCTIONAL, ANALYTICS, MARKETING, CONSENT_MANAGEMENT, UNKNOWN)

# Categories whose presence *before consent* is real evidence of a
# consent failure. Everything else is either allowed pre-consent
# (essential, consent_management), a judgement call (functional), or not
# known well enough to accuse anyone of anything (unknown).
CONSENT_REQUIRED_CATEGORIES = frozenset({ANALYTICS, MARKETING})

# Purposes — a finer-grained "why is this cookie here" label carried as
# evidence alongside the category (e.g. ESSENTIAL + "security").
PURPOSE_SESSION = "session"
PURPOSE_SECURITY = "security"            # CSRF/XSRF tokens
PURPOSE_LOAD_BALANCING = "load_balancing"
PURPOSE_BOT_PROTECTION = "bot_protection"
PURPOSE_CONSENT_STORAGE = "consent_storage"
PURPOSE_PREFERENCES = "preferences"
PURPOSE_MEASUREMENT = "measurement"
PURPOSE_ADVERTISING = "advertising"
PURPOSE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class CookieClassification:
    category: str
    purpose: str
    vendor: Optional[str] = None
    matched_by: str = "none"   # "name" | "pattern" | "domain" | "none"

    @property
    def requires_consent(self) -> bool:
        return self.category in CONSENT_REQUIRED_CATEGORIES


# --------------------------------------------------------------------------
# Exact names (lower-cased) -> (category, purpose, vendor)
# --------------------------------------------------------------------------
_EXACT_NAME_RULES = {
    # --- essential: sessions ---
    "session": (ESSENTIAL, PURPOSE_SESSION, None),
    "sessionid": (ESSENTIAL, PURPOSE_SESSION, None),
    "session_id": (ESSENTIAL, PURPOSE_SESSION, None),
    "sid": (ESSENTIAL, PURPOSE_SESSION, None),
    "phpsessid": (ESSENTIAL, PURPOSE_SESSION, "PHP"),
    "jsessionid": (ESSENTIAL, PURPOSE_SESSION, "Java"),
    "asp.net_sessionid": (ESSENTIAL, PURPOSE_SESSION, "ASP.NET"),
    "aspsessionid": (ESSENTIAL, PURPOSE_SESSION, "ASP"),
    "connect.sid": (ESSENTIAL, PURPOSE_SESSION, "Express"),
    "laravel_session": (ESSENTIAL, PURPOSE_SESSION, "Laravel"),
    "ci_session": (ESSENTIAL, PURPOSE_SESSION, "CodeIgniter"),

    # --- essential: security (CSRF / XSRF) ---
    "csrftoken": (ESSENTIAL, PURPOSE_SECURITY, None),
    "csrf_token": (ESSENTIAL, PURPOSE_SECURITY, None),
    "_csrf": (ESSENTIAL, PURPOSE_SECURITY, None),
    "csrf": (ESSENTIAL, PURPOSE_SECURITY, None),
    "xsrf-token": (ESSENTIAL, PURPOSE_SECURITY, None),
    "x-xsrf-token": (ESSENTIAL, PURPOSE_SECURITY, None),
    "__requestverificationtoken": (ESSENTIAL, PURPOSE_SECURITY, "ASP.NET"),

    # --- essential: load balancing ---
    "awsalb": (ESSENTIAL, PURPOSE_LOAD_BALANCING, "AWS"),
    "awsalbcors": (ESSENTIAL, PURPOSE_LOAD_BALANCING, "AWS"),
    "awsalbtg": (ESSENTIAL, PURPOSE_LOAD_BALANCING, "AWS"),
    "awsalbtgcors": (ESSENTIAL, PURPOSE_LOAD_BALANCING, "AWS"),
    "awselb": (ESSENTIAL, PURPOSE_LOAD_BALANCING, "AWS"),
    "arraffinity": (ESSENTIAL, PURPOSE_LOAD_BALANCING, "Azure"),
    "arraffinitysamesite": (ESSENTIAL, PURPOSE_LOAD_BALANCING, "Azure"),
    "route": (ESSENTIAL, PURPOSE_LOAD_BALANCING, None),

    # --- essential: bot / fraud protection ---
    "cf_clearance": (ESSENTIAL, PURPOSE_BOT_PROTECTION, "Cloudflare"),
    "__cf_bm": (ESSENTIAL, PURPOSE_BOT_PROTECTION, "Cloudflare"),
    "_cfuvid": (ESSENTIAL, PURPOSE_BOT_PROTECTION, "Cloudflare"),
    "__cflb": (ESSENTIAL, PURPOSE_LOAD_BALANCING, "Cloudflare"),
    "ak_bmsc": (ESSENTIAL, PURPOSE_BOT_PROTECTION, "Akamai"),
    "bm_sz": (ESSENTIAL, PURPOSE_BOT_PROTECTION, "Akamai"),
    "bm_sv": (ESSENTIAL, PURPOSE_BOT_PROTECTION, "Akamai"),
    "bm_mi": (ESSENTIAL, PURPOSE_BOT_PROTECTION, "Akamai"),
    "_abck": (ESSENTIAL, PURPOSE_BOT_PROTECTION, "Akamai"),
    "datadome": (ESSENTIAL, PURPOSE_BOT_PROTECTION, "DataDome"),

    # --- consent management: the CMP's own storage of the visitor's choice ---
    "optanonconsent": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "OneTrust"),
    "optanonalertboxclosed": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "OneTrust"),
    "otgppconsent": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "OneTrust"),
    "onetrust-consent": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "OneTrust"),
    "cookieconsent": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Cookiebot"),
    "cookieconsent_status": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Cookie Consent (Osano OSS)"),
    "cookie_consent": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, None),
    "cookie-consent": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, None),
    "cookie_consent_level": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, None),
    "euconsent": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "IAB TCF"),
    "euconsent-v2": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "IAB TCF"),
    "usprivacy": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "IAB CCPA"),
    "addtl_consent": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Google Additional Consent"),
    "didomi_token": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Didomi"),
    "consentuuid": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Sourcepoint"),
    "consentdate": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Sourcepoint"),
    "notice_preferences": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "TrustArc"),
    "notice_gdpr_prefs": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "TrustArc"),
    "notice_behavior": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "TrustArc"),
    "cmapi_cookie_privacy": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "TrustArc"),
    "cmapi_gtm_bl": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "TrustArc"),
    "osano_consentmanager": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Osano"),
    "osano_consentmanager_uuid": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Osano"),
    "consentmgr": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Tealium"),
    "axeptio_cookies": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Axeptio"),
    "axeptio_authorized_vendors": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Axeptio"),
    "axeptio_all_vendors": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Axeptio"),
    "borlabs-cookie": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Borlabs"),
    "moove_gdpr_popup": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Moove GDPR"),
    "uc_settings": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Usercentrics"),
    "uc_user_interaction": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Usercentrics"),
    "tarteaucitron": (CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "tarteaucitron"),

    # --- functional / preferences ---
    "lang": (FUNCTIONAL, PURPOSE_PREFERENCES, None),
    "language": (FUNCTIONAL, PURPOSE_PREFERENCES, None),
    "locale": (FUNCTIONAL, PURPOSE_PREFERENCES, None),
    "currency": (FUNCTIONAL, PURPOSE_PREFERENCES, None),
    "timezone": (FUNCTIONAL, PURPOSE_PREFERENCES, None),
    "theme": (FUNCTIONAL, PURPOSE_PREFERENCES, None),

    # --- analytics ---
    "_ga": (ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics"),
    "_gid": (ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics"),
    "_gat": (ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics"),
    "__utma": (ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics (legacy)"),
    "__utmb": (ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics (legacy)"),
    "__utmc": (ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics (legacy)"),
    "__utmz": (ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics (legacy)"),
    "_hjsessionuser": (ANALYTICS, PURPOSE_MEASUREMENT, "Hotjar"),
    "_hjsession": (ANALYTICS, PURPOSE_MEASUREMENT, "Hotjar"),
    "_hjincludedinsessionsample": (ANALYTICS, PURPOSE_MEASUREMENT, "Hotjar"),
    "_clck": (ANALYTICS, PURPOSE_MEASUREMENT, "Microsoft Clarity"),
    "_clsk": (ANALYTICS, PURPOSE_MEASUREMENT, "Microsoft Clarity"),
    "amplitude_id": (ANALYTICS, PURPOSE_MEASUREMENT, "Amplitude"),
    "mp_mixpanel": (ANALYTICS, PURPOSE_MEASUREMENT, "Mixpanel"),
    "__hstc": (ANALYTICS, PURPOSE_MEASUREMENT, "HubSpot"),
    "_scid": (ANALYTICS, PURPOSE_MEASUREMENT, "Snapchat"),
    "s_cc": (ANALYTICS, PURPOSE_MEASUREMENT, "Adobe Analytics"),
    "s_sq": (ANALYTICS, PURPOSE_MEASUREMENT, "Adobe Analytics"),
    "s_vi": (ANALYTICS, PURPOSE_MEASUREMENT, "Adobe Analytics"),
    "s_fid": (ANALYTICS, PURPOSE_MEASUREMENT, "Adobe Analytics"),
    "_pk_id": (ANALYTICS, PURPOSE_MEASUREMENT, "Matomo"),
    "_pk_ses": (ANALYTICS, PURPOSE_MEASUREMENT, "Matomo"),

    # --- marketing / advertising ---
    "_fbp": (MARKETING, PURPOSE_ADVERTISING, "Meta"),
    "_fbc": (MARKETING, PURPOSE_ADVERTISING, "Meta"),
    "fr": (MARKETING, PURPOSE_ADVERTISING, "Meta"),
    "ide": (MARKETING, PURPOSE_ADVERTISING, "Google DoubleClick"),
    "dsid": (MARKETING, PURPOSE_ADVERTISING, "Google DoubleClick"),
    "test_cookie": (MARKETING, PURPOSE_ADVERTISING, "Google DoubleClick"),
    "muid": (MARKETING, PURPOSE_ADVERTISING, "Microsoft"),
    "_ttp": (MARKETING, PURPOSE_ADVERTISING, "TikTok"),
    "_uetsid": (MARKETING, PURPOSE_ADVERTISING, "Microsoft Ads"),
    "_uetvid": (MARKETING, PURPOSE_ADVERTISING, "Microsoft Ads"),
    "nid": (MARKETING, PURPOSE_ADVERTISING, "Google"),
    "_gads": (MARKETING, PURPOSE_ADVERTISING, "Google AdSense"),
    "personalization_id": (MARKETING, PURPOSE_ADVERTISING, "X / Twitter"),
    "li_sugr": (MARKETING, PURPOSE_ADVERTISING, "LinkedIn"),
    "bcookie": (MARKETING, PURPOSE_ADVERTISING, "LinkedIn"),
    "bscookie": (MARKETING, PURPOSE_ADVERTISING, "LinkedIn"),
    "lidc": (MARKETING, PURPOSE_ADVERTISING, "LinkedIn"),
    "hubspotutk": (MARKETING, PURPOSE_ADVERTISING, "HubSpot"),
    "_pin_unauth": (MARKETING, PURPOSE_ADVERTISING, "Pinterest"),
}

# (regex, category, purpose, vendor) for names with variable suffixes —
# checked in order, first match wins.
_PATTERN_RULES = [
    # consent management families
    (re.compile(r"^cookieyes-"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "CookieYes"),
    (re.compile(r"^cookielawinfo-"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "CookieLawInfo"),
    (re.compile(r"^_iub_cs-"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "iubenda"),
    (re.compile(r"^cmplz_"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Complianz"),
    (re.compile(r"^__cmpcc"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "consentmanager.net"),
    (re.compile(r"^__cmpconsent"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "consentmanager.net"),
    (re.compile(r"^_sp_(su|enable_dfp|v1_)"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Sourcepoint"),
    (re.compile(r"^cookiefirst-"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "CookieFirst"),
    (re.compile(r"^klaro"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Klaro"),

    # analytics / marketing families
    (re.compile(r"^_ga_[a-z0-9]+$"), ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics"),
    (re.compile(r"^_gat_"), ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics"),
    (re.compile(r"^_hj"), ANALYTICS, PURPOSE_MEASUREMENT, "Hotjar"),
    (re.compile(r"^amp_"), ANALYTICS, PURPOSE_MEASUREMENT, "Amplitude"),
    (re.compile(r"^mp_[0-9a-f]+_mixpanel$"), ANALYTICS, PURPOSE_MEASUREMENT, "Mixpanel"),
    (re.compile(r"^amcv_"), ANALYTICS, PURPOSE_MEASUREMENT, "Adobe Experience Cloud"),
    (re.compile(r"^amcvs_"), ANALYTICS, PURPOSE_MEASUREMENT, "Adobe Experience Cloud"),
    (re.compile(r"^_pk_"), ANALYTICS, PURPOSE_MEASUREMENT, "Matomo"),
    (re.compile(r"^_gcl_"), MARKETING, PURPOSE_ADVERTISING, "Google Ads"),
    (re.compile(r"^__hs"), MARKETING, PURPOSE_ADVERTISING, "HubSpot"),
    (re.compile(r"^_tt_"), MARKETING, PURPOSE_ADVERTISING, "TikTok"),

    # essential: security / session families
    (re.compile(r"^__host-"), ESSENTIAL, PURPOSE_SECURITY, None),
    (re.compile(r"^__secure-.*(csrf|xsrf|session)"), ESSENTIAL, PURPOSE_SECURITY, None),
    (re.compile(r"(^|[_.-])(csrf|xsrf)([_.-]|$)"), ESSENTIAL, PURPOSE_SECURITY, None),
    (re.compile(r"(csrf|xsrf)"), ESSENTIAL, PURPOSE_SECURITY, None),
    (re.compile(r"^aspsessionid"), ESSENTIAL, PURPOSE_SESSION, "ASP"),
    (re.compile(r"(^|[_.-])session(id)?([_.-]|$)"), ESSENTIAL, PURPOSE_SESSION, None),
    (re.compile(r"^incap_ses_"), ESSENTIAL, PURPOSE_BOT_PROTECTION, "Imperva"),
    (re.compile(r"^visid_incap_"), ESSENTIAL, PURPOSE_BOT_PROTECTION, "Imperva"),
    (re.compile(r"^nlbi_"), ESSENTIAL, PURPOSE_LOAD_BALANCING, "Imperva"),
    (re.compile(r"^ts01[0-9a-f]+$"), ESSENTIAL, PURPOSE_BOT_PROTECTION, "F5"),
    (re.compile(r"^bigipserver"), ESSENTIAL, PURPOSE_LOAD_BALANCING, "F5"),
    (re.compile(r"^__stripe_"), ESSENTIAL, PURPOSE_BOT_PROTECTION, "Stripe"),
    (re.compile(r"^wordpress_logged_in"), ESSENTIAL, PURPOSE_SESSION, "WordPress"),
    (re.compile(r"^wordpress_sec_"), ESSENTIAL, PURPOSE_SECURITY, "WordPress"),
    (re.compile(r"^wp-settings"), FUNCTIONAL, PURPOSE_PREFERENCES, "WordPress"),
]

# Domains whose cookies are near-certainly one category regardless of
# the exact cookie name.
_DOMAIN_HINTS = [
    (re.compile(r"(^|\.)doubleclick\.net$"), MARKETING, PURPOSE_ADVERTISING, "Google DoubleClick"),
    (re.compile(r"(^|\.)googlesyndication\.com$"), MARKETING, PURPOSE_ADVERTISING, "Google AdSense"),
    (re.compile(r"(^|\.)googleadservices\.com$"), MARKETING, PURPOSE_ADVERTISING, "Google Ads"),
    (re.compile(r"(^|\.)facebook\.com$"), MARKETING, PURPOSE_ADVERTISING, "Meta"),
    (re.compile(r"(^|\.)ads-twitter\.com$"), MARKETING, PURPOSE_ADVERTISING, "X / Twitter"),
    (re.compile(r"(^|\.)linkedin\.com$"), MARKETING, PURPOSE_ADVERTISING, "LinkedIn"),
    (re.compile(r"(^|\.)adsrvr\.org$"), MARKETING, PURPOSE_ADVERTISING, "The Trade Desk"),
    (re.compile(r"(^|\.)bing\.com$"), MARKETING, PURPOSE_ADVERTISING, "Microsoft Ads"),
    (re.compile(r"(^|\.)google-analytics\.com$"), ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics"),
    (re.compile(r"(^|\.)analytics\.google\.com$"), ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics"),
    (re.compile(r"(^|\.)hotjar\.com$"), ANALYTICS, PURPOSE_MEASUREMENT, "Hotjar"),
    (re.compile(r"(^|\.)clarity\.ms$"), ANALYTICS, PURPOSE_MEASUREMENT, "Microsoft Clarity"),
    (re.compile(r"(^|\.)cookielaw\.org$"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "OneTrust"),
    (re.compile(r"(^|\.)onetrust\.com$"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "OneTrust"),
    (re.compile(r"(^|\.)cookiebot\.com$"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Cookiebot"),
]

DISPLAY_NAMES = {
    ESSENTIAL: "Strictly necessary",
    FUNCTIONAL: "Functional",
    ANALYTICS: "Analytics",
    MARKETING: "Marketing / advertising",
    CONSENT_MANAGEMENT: "Consent management",
    UNKNOWN: "Unknown",
}

PURPOSE_DISPLAY_NAMES = {
    PURPOSE_SESSION: "Session",
    PURPOSE_SECURITY: "Security (CSRF/XSRF)",
    PURPOSE_LOAD_BALANCING: "Load balancing",
    PURPOSE_BOT_PROTECTION: "Bot / fraud protection",
    PURPOSE_CONSENT_STORAGE: "Consent preference storage",
    PURPOSE_PREFERENCES: "User preferences",
    PURPOSE_MEASUREMENT: "Measurement",
    PURPOSE_ADVERTISING: "Advertising",
    PURPOSE_UNKNOWN: "Unknown",
}


def classify_cookie(name: str, domain: Optional[str] = None) -> CookieClassification:
    """
    Full classification of one cookie: category, purpose, vendor and how
    it was matched. Precedence: exact name, name pattern, domain hint,
    then UNKNOWN. Case-insensitive on name and domain.
    """
    key = (name or "").strip().lower()
    if not key:
        return CookieClassification(UNKNOWN, PURPOSE_UNKNOWN)

    rule = _EXACT_NAME_RULES.get(key)
    if rule:
        return CookieClassification(rule[0], rule[1], rule[2], "name")

    for pattern, category, purpose, vendor in _PATTERN_RULES:
        if pattern.search(key):
            return CookieClassification(category, purpose, vendor, "pattern")

    if domain:
        dom = domain.strip().lower().lstrip(".")
        for pattern, category, purpose, vendor in _DOMAIN_HINTS:
            if pattern.search(dom):
                return CookieClassification(category, purpose, vendor, "domain")

    return CookieClassification(UNKNOWN, PURPOSE_UNKNOWN)


def categorize_cookie(name: str, domain: Optional[str] = None) -> str:
    """Category only — kept for every existing caller of this module."""
    return classify_cookie(name, domain).category


def requires_consent(category: str) -> bool:
    """True only for categories whose pre-consent presence is real evidence of a failure."""
    return category in CONSENT_REQUIRED_CATEGORIES


def display_name(category: str) -> str:
    return DISPLAY_NAMES.get(category, category.replace("_", " ").title())


def purpose_display_name(purpose: str) -> str:
    return PURPOSE_DISPLAY_NAMES.get(purpose, purpose.replace("_", " ").title())
