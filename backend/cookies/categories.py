"""
Classifies a cookie by name (and domain):
  essential          - sessions, CSRF tokens, load balancing, bot protection
  functional         - visitor preferences (language, currency, theme)
  analytics          - measurement
  marketing          - advertising, retargeting, social pixels
  consent_management - the consent tool storing the visitor's choice
  unknown            - not recognised

Unknown stays unknown (a wrong guess is worse); report it as "needs review".
requires_consent() is True only for analytics and marketing.
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

# Categories whose presence before consent is a real consent failure.
CONSENT_REQUIRED_CATEGORIES = frozenset({ANALYTICS, MARKETING})

# Purpose: a finer "why is this cookie here" label shown with the category.
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


# Exact names (lower case) -> (category, purpose, vendor)
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

    # --- consent management: the consent tool's own storage ---
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

# (regex, category, purpose, vendor) for names with variable parts; first match wins.
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
    (re.compile(r"^_evidon_"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE, "Evidon (Crownpeak)"),
    (re.compile(r"^tc_privacy(_center)?$|^tcpid$"), CONSENT_MANAGEMENT, PURPOSE_CONSENT_STORAGE,
     "TrustCommander (Commanders Act)"),

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
    # A/B testing, session replay and experience analytics
    (re.compile(r"^_vwo|^_vis_opt|^_vwo_"), ANALYTICS, PURPOSE_MEASUREMENT, "VWO (A/B testing)"),
    (re.compile(r"^optimizely"), ANALYTICS, PURPOSE_MEASUREMENT, "Optimizely"),
    (re.compile(r"^kameleoon"), ANALYTICS, PURPOSE_MEASUREMENT, "Kameleoon"),
    (re.compile(r"^abtasty"), ANALYTICS, PURPOSE_MEASUREMENT, "AB Tasty"),
    (re.compile(r"^mbox$|^at_check$"), ANALYTICS, PURPOSE_MEASUREMENT, "Adobe Target"),
    (re.compile(r"^s_(ecid|ppv|plt|pltp|nr|tp|ips|getnewrepeat|lv|lv_s|invisit|visit|dfa|campaign)"), ANALYTICS,
     PURPOSE_MEASUREMENT, "Adobe Analytics"),
    (re.compile(r"^_cs_|^_cs_c$"), ANALYTICS, PURPOSE_MEASUREMENT, "Contentsquare"),
    (re.compile(r"^mf_"), ANALYTICS, PURPOSE_MEASUREMENT, "Mouseflow"),
    (re.compile(r"^quantummetric"), ANALYTICS, PURPOSE_MEASUREMENT, "Quantum Metric"),
    (re.compile(r"^(dtcookie|dtpc|dtlatc|dtsa|rxvisitor|rxvt)$"), ANALYTICS, PURPOSE_MEASUREMENT, "Dynatrace"),
    (re.compile(r"^rt$"), ANALYTICS, PURPOSE_MEASUREMENT, "Akamai mPulse"),
    (re.compile(r"^_ym_"), ANALYTICS, PURPOSE_MEASUREMENT, "Yandex Metrica"),
    (re.compile(r"^ajs_"), ANALYTICS, PURPOSE_MEASUREMENT, "Segment"),
    (re.compile(r"^_hp2_"), ANALYTICS, PURPOSE_MEASUREMENT, "Heap"),
    (re.compile(r"^_sp_(id|ses)"), ANALYTICS, PURPOSE_MEASUREMENT, "Snowplow"),
    (re.compile(r"^_pk|^_pk_"), ANALYTICS, PURPOSE_MEASUREMENT, "Matomo / Piwik PRO"),
    (re.compile(r"^tc_cj_v2"), ANALYTICS, PURPOSE_MEASUREMENT, "Commanders Act"),
    (re.compile(r"^_clck|^_clsk|^clid$"), ANALYTICS, PURPOSE_MEASUREMENT, "Microsoft Clarity"),
    (re.compile(r"^__qca$"), MARKETING, PURPOSE_ADVERTISING, "Quantcast"),
    (re.compile(r"^cto_"), MARKETING, PURPOSE_ADVERTISING, "Criteo"),
    (re.compile(r"^t_gid$|^taboola"), MARKETING, PURPOSE_ADVERTISING, "Taboola"),
    (re.compile(r"^obuid$|^outbrain"), MARKETING, PURPOSE_ADVERTISING, "Outbrain"),
    (re.compile(r"^tdid$|^tdcpm$|^tdrid$"), MARKETING, PURPOSE_ADVERTISING, "The Trade Desk"),
    (re.compile(r"^visitor_id\d+|^pi_opt_in"), MARKETING, PURPOSE_ADVERTISING, "Salesforce Pardot"),
    (re.compile(r"^_rdt_"), MARKETING, PURPOSE_ADVERTISING, "Reddit"),
    (re.compile(r"^_pin"), MARKETING, PURPOSE_ADVERTISING, "Pinterest"),
    (re.compile(r"^_scid|^sc_at$"), MARKETING, PURPOSE_ADVERTISING, "Snapchat"),
    (re.compile(r"^demdex$|^dextp$|^dst$"), MARKETING, PURPOSE_ADVERTISING, "Adobe Audience Manager"),
    (re.compile(r"^everest_|^ev_sync"), MARKETING, PURPOSE_ADVERTISING, "Adobe Advertising"),
    (re.compile(r"^uuid2$|^anj$"), MARKETING, PURPOSE_ADVERTISING, "Xandr"),
    (re.compile(r"^__zlcmid$|^intercom-"), FUNCTIONAL, PURPOSE_PREFERENCES, "Chat widget"),
    (re.compile(r"^webchat|^livechat|^lc_"), FUNCTIONAL, PURPOSE_PREFERENCES, "Chat widget"),
    (re.compile(r"^fpid$|^fplc$"), ANALYTICS, PURPOSE_MEASUREMENT, "Google Analytics (first-party mode)"),
    (re.compile(r"^fpau$|^fpgcl"), MARKETING, PURPOSE_ADVERTISING, "Google Ads (first-party mode)"),
    (re.compile(r"^uet_vid|^_uetmsclkid|^_uetvid|^_uetsid"), MARKETING, PURPOSE_ADVERTISING, "Microsoft Ads"),
    (re.compile(r"^_gtmeec"), MARKETING, PURPOSE_ADVERTISING, "Server-side GTM (conversions)"),

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

# Domains whose cookies are almost always one category.
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
    (re.compile(r"(^|\.)visualwebsiteoptimizer\.com$"), ANALYTICS, PURPOSE_MEASUREMENT, "VWO (A/B testing)"),
    (re.compile(r"(^|\.)omtrdc\.net$|(^|\.)2o7\.net$"), ANALYTICS, PURPOSE_MEASUREMENT, "Adobe Analytics"),
    (re.compile(r"(^|\.)contentsquare\.net$"), ANALYTICS, PURPOSE_MEASUREMENT, "Contentsquare"),
    (re.compile(r"(^|\.)dynatrace\.com$"), ANALYTICS, PURPOSE_MEASUREMENT, "Dynatrace"),
    (re.compile(r"(^|\.)demdex\.net$"), MARKETING, PURPOSE_ADVERTISING, "Adobe Audience Manager"),
    (re.compile(r"(^|\.)everesttech\.net$"), MARKETING, PURPOSE_ADVERTISING, "Adobe Advertising"),
    (re.compile(r"(^|\.)criteo\.com$"), MARKETING, PURPOSE_ADVERTISING, "Criteo"),
    (re.compile(r"(^|\.)adnxs\.com$"), MARKETING, PURPOSE_ADVERTISING, "Xandr"),
    (re.compile(r"(^|\.)(taboola|outbrain)\.com$"), MARKETING, PURPOSE_ADVERTISING, "Native ads"),
    (re.compile(r"(^|\.)tiktok\.com$"), MARKETING, PURPOSE_ADVERTISING, "TikTok"),
    (re.compile(r"(^|\.)pinterest\.com$"), MARKETING, PURPOSE_ADVERTISING, "Pinterest"),
    (re.compile(r"(^|\.)yandex\.(ru|com)$"), ANALYTICS, PURPOSE_MEASUREMENT, "Yandex Metrica"),
    (re.compile(r"(^|\.)(rubiconproject|pubmatic|casalemedia|openx)\.(com|net)$"), MARKETING, PURPOSE_ADVERTISING,
     "Ad exchange"),
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
    """Category, purpose and vendor for one cookie. Order: exact name, name pattern, domain, then unknown."""
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
    """Category only (older callers)."""
    return classify_cookie(name, domain).category


def requires_consent(category: str) -> bool:
    """True only for analytics and marketing."""
    return category in CONSENT_REQUIRED_CATEGORIES


def display_name(category: str) -> str:
    return DISPLAY_NAMES.get(category, category.replace("_", " ").title())


def purpose_display_name(purpose: str) -> str:
    return PURPOSE_DISPLAY_NAMES.get(purpose, purpose.replace("_", " ").title())
