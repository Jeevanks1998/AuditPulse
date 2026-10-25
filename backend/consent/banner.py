"""
Finds a cookie banner in the raw HTML: a known consent tool (CMP) or a
generic id/class/text match. Banners added later by JavaScript are found by
the browser check (runtime.py). Buttons and preferences are checked elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "consent"
CATEGORY = "banner"

# (key, name, regex for class/id, regex for script src)
_CMP_SIGNATURES = [
    ("onetrust", "OneTrust", re.compile(r"onetrust|optanon", re.IGNORECASE),
     re.compile(r"cdn\.cookielaw\.org|onetrust\.com", re.IGNORECASE)),
    ("cookiebot", "Cookiebot", re.compile(r"cookiebot|CybotCookiebot", re.IGNORECASE),
     re.compile(r"consent\.cookiebot\.com", re.IGNORECASE)),
    ("cookieyes", "CookieYes", re.compile(r"cky-consent|cookieyes", re.IGNORECASE),
     re.compile(r"cdn-cookieyes\.com", re.IGNORECASE)),
    ("osano", "Osano", re.compile(r"osano-cm", re.IGNORECASE),
     re.compile(r"cmp\.osano\.com", re.IGNORECASE)),
    ("trustarc", "TrustArc", re.compile(r"trustarc|truste-", re.IGNORECASE),
     re.compile(r"consent\.trustarc\.com", re.IGNORECASE)),
    ("quantcast", "Quantcast Choice", re.compile(r"qc-cmp", re.IGNORECASE),
     re.compile(r"quantcast\.mgr\.consensu\.org", re.IGNORECASE)),
    ("iubenda", "iubenda", re.compile(r"iubenda-cs|iub_cs", re.IGNORECASE),
     re.compile(r"cdn\.iubenda\.com", re.IGNORECASE)),
    ("complianz", "Complianz", re.compile(r"cmplz-", re.IGNORECASE),
     re.compile(r"complianz", re.IGNORECASE)),
    ("didomi", "Didomi", re.compile(r"didomi-", re.IGNORECASE),
     re.compile(r"sdk\.privacy-center\.org|didomi\.io", re.IGNORECASE)),
    ("trustcommander", "TrustCommander (Commanders Act)", re.compile(r"tc-privacy|footer_tc_privacy|tc_privacy", re.IGNORECASE),
     re.compile(r"trustcommander\.net", re.IGNORECASE)),
    ("evidon", "Evidon (Crownpeak)", re.compile(r"_evidon|evidon-banner|evidon-barrier", re.IGNORECASE),
     re.compile(r"evidon\.com|betrad\.com", re.IGNORECASE)),
    ("usercentrics", "Usercentrics", re.compile(r"usercentrics|uc-center", re.IGNORECASE),
     re.compile(r"usercentrics\.eu|usercentrics\.com", re.IGNORECASE)),
    ("sourcepoint", "Sourcepoint", re.compile(r"sp_message_container", re.IGNORECASE),
     re.compile(r"privacy-mgmt\.com|sourcepoint", re.IGNORECASE)),
    ("axeptio", "Axeptio", re.compile(r"axeptio", re.IGNORECASE), re.compile(r"axept\.io", re.IGNORECASE)),
    ("consentmanager", "consentmanager", re.compile(r"cmpbox|cmpwrapper", re.IGNORECASE),
     re.compile(r"consentmanager\.net", re.IGNORECASE)),
]

# Generic id/class that suggests a home-made banner.
_GENERIC_MARKUP_RE = re.compile(
    r"cookie[-_]?(banner|consent|notice|bar|popup)|consent[-_]?(banner|bar|popup)",
    re.IGNORECASE,
)
_GENERIC_TEXT_RE = re.compile(
    r"we use cookies|this (site|website) uses cookies|by continuing to (browse|use) (this|our) (site|website)",
    re.IGNORECASE,
)


@dataclass
class BannerDetection:
    detected: bool = False
    cmp_key: Optional[str] = None            # e.g. "onetrust"; None if home-made
    cmp_name: Optional[str] = None           # e.g. "OneTrust"
    detected_via: List[str] = field(default_factory=list)  # ["markup", "script", "text"]
    element_hint: Optional[str] = None       # id/class of the banner, for the screenshot


def detect_banner(page: ParsedPage) -> BannerDetection:
    result = BannerDetection()

    scripts_text = " ".join(tag.get("src") or "" for tag in page.soup.find_all("script"))

    for key, name, markup_re, script_re in _CMP_SIGNATURES:
        matched_element = _find_markup_match(page, markup_re)
        script_match = script_re.search(scripts_text)
        if matched_element or script_match:
            result.detected = True
            result.cmp_key = key
            result.cmp_name = name
            if matched_element:
                result.detected_via.append("markup")
                result.element_hint = matched_element
            if script_match:
                result.detected_via.append("script")
            return result

    generic_element = _find_markup_match(page, _GENERIC_MARKUP_RE)
    if generic_element:
        result.detected = True
        result.detected_via.append("markup")
        result.element_hint = generic_element
        return result

    if page.text_content and _GENERIC_TEXT_RE.search(page.text_content):
        result.detected = True
        result.detected_via.append("text")

    return result


def check_banner(page: ParsedPage) -> List[dict]:
    detection = detect_banner(page)
    if detection.detected:
        return []
    return [{
        "module": MODULE,
        "category": CATEGORY,
        "severity": "critical",
        "title": "No cookie-consent banner detected",
        "description": f"{page.url} shows no recognizable consent banner or CMP markup. If "
                        "this page sets non-essential cookies, this is likely a GDPR/ePrivacy "
                        "compliance gap.",
        "recommendation": "Add a consent banner (a CMP like OneTrust/Cookiebot, or a compliant "
                           "custom implementation) before any non-essential cookies are set.",
    }]


def _find_markup_match(page: ParsedPage, pattern: re.Pattern) -> Optional[str]:
    for tag in page.soup.find_all(True):
        for attr in ("id", "class"):
            value = tag.get(attr)
            if not value:
                continue
            joined = value if isinstance(value, str) else " ".join(value)
            if pattern.search(joined):
                return f"{attr}={joined!r}"
    return None
