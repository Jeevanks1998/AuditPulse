"""
Records every request a page makes before any cookie button is clicked,
and sorts each request (also used by runtime.py).

Category: CMP, TAG_MANAGER, ANALYTICS, ADVERTISING, SOCIAL, CONTENT_CDN,
FONT, OTHER_THIRD_PARTY, FIRST_PARTY or UNKNOWN.
Activity: collection (a data-collection hit: the only real tracking),
loader (a library download), embed, infrastructure / content.

So "GTM loaded" is only an observation; a Google Analytics collection hit is
tracking. tracker_requests returns only real tracking.
If the browser can't run, results are empty, never an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from config.logging import logger
from config.browser import launch_chromium

NAVIGATION_TIMEOUT_MS = 20_000
SETTLE_MS = 1_500  # short wait after load for delayed requests

# Categories
CMP = "CMP"
TAG_MANAGER = "TAG_MANAGER"
ANALYTICS = "ANALYTICS"
ADVERTISING = "ADVERTISING"
SOCIAL = "SOCIAL"
OTHER_THIRD_PARTY = "OTHER_THIRD_PARTY"
CONTENT_CDN = "CONTENT_CDN"
FONT = "FONT"
FIRST_PARTY = "FIRST_PARTY"
UNKNOWN = "UNKNOWN"

REQUEST_CATEGORIES = (
    CMP, TAG_MANAGER, ANALYTICS, ADVERTISING, SOCIAL,
    OTHER_THIRD_PARTY, CONTENT_CDN, FONT, FIRST_PARTY, UNKNOWN,
)

CATEGORY_LABELS = {
    CMP: "Consent platform (CMP)",
    TAG_MANAGER: "Tag manager",
    ANALYTICS: "Analytics",
    ADVERTISING: "Advertising",
    SOCIAL: "Social",
    OTHER_THIRD_PARTY: "Other third party",
    CONTENT_CDN: "Content / CDN",
    FONT: "Font",
    FIRST_PARTY: "First party",
    UNKNOWN: "Unknown",
}

# Activities
COLLECTION = "collection"
LOADER = "loader"
EMBED = "embed"
INFRASTRUCTURE = "infrastructure"
CONTENT = "content"

_TRACKING_CATEGORIES = frozenset({ANALYTICS, ADVERTISING})
_LOADER_RESOURCE_TYPES = frozenset({"script", "stylesheet", "document"})

# Rules: (domain suffix, path regex or None, category, vendor, activity or None).
# First match wins, so specific rules come before a domain's general rule.
# activity None = from the request type (script -> loader, others -> collection).
_RULES: List[Tuple[str, Optional[re.Pattern], str, str, Optional[str]]] = []


def _r(domain: str, path: Optional[str], category: str, vendor: str, activity: Optional[str] = None) -> None:
    _RULES.append((domain, re.compile(path, re.IGNORECASE) if path else None, category, vendor, activity))


# Consent tools (CMPs)
for _d, _v in [
    ("cookielaw.org", "OneTrust"), ("onetrust.com", "OneTrust"), ("onetrust.io", "OneTrust"),
    ("cookiebot.com", "Cookiebot"), ("cookiebot.eu", "Cookiebot"),
    ("cdn-cookieyes.com", "CookieYes"), ("cookieyes.com", "CookieYes"),
    ("osano.com", "Osano"), ("trustarc.com", "TrustArc"), ("truste.com", "TrustArc"),
    ("consensu.org", "IAB TCF CMP"), ("quantcast.com", "Quantcast Choice"),
    ("iubenda.com", "iubenda"), ("privacy-center.org", "Didomi"), ("didomi.io", "Didomi"),
    ("usercentrics.eu", "Usercentrics"), ("usercentrics.com", "Usercentrics"),
    ("consentmanager.net", "consentmanager.net"), ("privacy-mgmt.com", "Sourcepoint"),
    ("sourcepoint.com", "Sourcepoint"), ("fundingchoicesmessages.google.com", "Google Funding Choices"),
    ("axept.io", "Axeptio"), ("cookiefirst.com", "CookieFirst"), ("termly.io", "Termly"),
    ("trustcommander.net", "TrustCommander (Commanders Act)"),
    ("evidon.com", "Evidon (Crownpeak)"), ("betrad.com", "Evidon (Crownpeak)"),
]:
    _r(_d, None, CMP, _v, INFRASTRUCTURE)

# Tag managers (loading one is not tracking)
_r("googletagmanager.com", r"/g/collect|/collect\b", ANALYTICS, "Google Analytics", COLLECTION)
_r("googletagmanager.com", None, TAG_MANAGER, "Google Tag Manager", LOADER)
_r("tiqcdn.com", None, TAG_MANAGER, "Tealium iQ", LOADER)
_r("adobedtm.com", None, TAG_MANAGER, "Adobe Launch", LOADER)
_r("tagcommander.com", None, TAG_MANAGER, "Commanders Act", LOADER)
_r("commander1.com", None, TAG_MANAGER, "Commanders Act", LOADER)
_r("ensighten.com", None, TAG_MANAGER, "Ensighten", LOADER)
_r("segment.com", None, TAG_MANAGER, "Segment", LOADER)

# Analytics
_r("google-analytics.com", r"/(g/|j/|r/)?collect|/__utm\.gif", ANALYTICS, "Google Analytics", COLLECTION)
_r("google-analytics.com", r"\.js$", ANALYTICS, "Google Analytics", LOADER)
_r("google-analytics.com", None, ANALYTICS, "Google Analytics")
_r("analytics.google.com", None, ANALYTICS, "Google Analytics", COLLECTION)
_r("hotjar.com", r"^/c/hotjar-|\.js$", ANALYTICS, "Hotjar", LOADER)
_r("hotjar.com", None, ANALYTICS, "Hotjar")
_r("hotjar.io", None, ANALYTICS, "Hotjar", COLLECTION)
_r("clarity.ms", r"^/(tag|s)/", ANALYTICS, "Microsoft Clarity", LOADER)
_r("clarity.ms", r"/collect", ANALYTICS, "Microsoft Clarity", COLLECTION)
_r("clarity.ms", None, ANALYTICS, "Microsoft Clarity")
_r("hs-scripts.com", None, ANALYTICS, "HubSpot", LOADER)
_r("hs-analytics.net", r"\.js$", ANALYTICS, "HubSpot", LOADER)
_r("hs-analytics.net", None, ANALYTICS, "HubSpot")
_r("hubspot.com", r"__ptq\.gif|/collect", ANALYTICS, "HubSpot", COLLECTION)
_r("segment.io", None, ANALYTICS, "Segment", COLLECTION)
_r("mixpanel.com", None, ANALYTICS, "Mixpanel")
_r("amplitude.com", None, ANALYTICS, "Amplitude")
_r("heapanalytics.com", None, ANALYTICS, "Heap")
_r("fullstory.com", None, ANALYTICS, "FullStory")
_r("mouseflow.com", None, ANALYTICS, "Mouseflow")
_r("crazyegg.com", None, ANALYTICS, "Crazy Egg")
_r("omtrdc.net", None, ANALYTICS, "Adobe Analytics", COLLECTION)
_r("2o7.net", None, ANALYTICS, "Adobe Analytics", COLLECTION)
_r("xiti.com", None, ANALYTICS, "Piano Analytics", COLLECTION)
_r("pa-cd.com", None, ANALYTICS, "Piano Analytics", COLLECTION)
_r("aticdn.net", None, ANALYTICS, "Piano Analytics", LOADER)
_r("at-o.net", None, ANALYTICS, "Piano Analytics")
_r("piano.io", None, ANALYTICS, "Piano Analytics")
_r("scorecardresearch.com", None, ANALYTICS, "Comscore")
_r("matomo.cloud", None, ANALYTICS, "Matomo")
_r("plausible.io", None, ANALYTICS, "Plausible")
_r("newrelic.com", None, ANALYTICS, "New Relic")
_r("nr-data.net", None, ANALYTICS, "New Relic", COLLECTION)
_r("contentsquare.net", r"\.js$", ANALYTICS, "Contentsquare", LOADER)
_r("contentsquare.net", None, ANALYTICS, "Contentsquare", COLLECTION)
_r("abtasty.com", None, ANALYTICS, "AB Tasty")
_r("kameleoon.eu", None, ANALYTICS, "Kameleoon")
_r("kameleoon.io", None, ANALYTICS, "Kameleoon")
_r("eulerian.net", None, ANALYTICS, "Eulerian")
_r("dynatrace.com", None, ANALYTICS, "Dynatrace")
_r("quantummetric.com", None, ANALYTICS, "Quantum Metric")
_r("optimizely.com", None, ANALYTICS, "Optimizely")
_r("qualtrics.com", None, ANALYTICS, "Qualtrics")
_r("kampyle.com", None, ANALYTICS, "Medallia")
_r("medallia.eu", r"/api/web/events|/events?\b", ANALYTICS, "Medallia", COLLECTION)
_r("medallia.eu", None, ANALYTICS, "Medallia", LOADER)
_r("medallia.com", r"/api/web/events|/events?\b", ANALYTICS, "Medallia", COLLECTION)
_r("medallia.com", None, ANALYTICS, "Medallia", LOADER)
_r("matomo.org", None, ANALYTICS, "Matomo")

# Advertising
_r("connect.facebook.net", None, ADVERTISING, "Meta Pixel", LOADER)
_r("facebook.com", r"^/tr/?$", ADVERTISING, "Meta Pixel", COLLECTION)
_r("facebook.com", r"^/plugins/|^/v[0-9.]+/plugins/", SOCIAL, "Meta", EMBED)
_r("facebook.com", None, ADVERTISING, "Meta")
_r("doubleclick.net", None, ADVERTISING, "Google Ads / DoubleClick", COLLECTION)
_r("googlesyndication.com", None, ADVERTISING, "Google AdSense")
_r("googleadservices.com", None, ADVERTISING, "Google Ads")
_r("adservice.google.com", None, ADVERTISING, "Google Ads", COLLECTION)
_r("google.com", r"^/pagead/|^/ads/", ADVERTISING, "Google Ads", COLLECTION)
_r("analytics.tiktok.com", r"/api/", ADVERTISING, "TikTok Pixel", COLLECTION)
_r("analytics.tiktok.com", None, ADVERTISING, "TikTok Pixel")
_r("static.ads-twitter.com", None, ADVERTISING, "Twitter/X Ads", LOADER)
_r("ads-twitter.com", None, ADVERTISING, "Twitter/X Ads")
_r("analytics.twitter.com", None, ADVERTISING, "Twitter/X Ads", COLLECTION)
_r("t.co", r"^/i/adsct", ADVERTISING, "Twitter/X Ads", COLLECTION)
_r("snap.licdn.com", None, ADVERTISING, "LinkedIn Insight", LOADER)
_r("ads.linkedin.com", None, ADVERTISING, "LinkedIn Insight", COLLECTION)
_r("bat.bing.com", r"bat\.js$", ADVERTISING, "Microsoft Advertising", LOADER)
_r("bat.bing.com", None, ADVERTISING, "Microsoft Advertising", COLLECTION)
_r("adsrvr.org", None, ADVERTISING, "The Trade Desk")
_r("criteo.com", None, ADVERTISING, "Criteo")
_r("criteo.net", None, ADVERTISING, "Criteo")
_r("taboola.com", None, ADVERTISING, "Taboola")
_r("outbrain.com", None, ADVERTISING, "Outbrain")
_r("amazon-adsystem.com", None, ADVERTISING, "Amazon Ads")
_r("adnxs.com", None, ADVERTISING, "Xandr")
_r("rubiconproject.com", None, ADVERTISING, "Magnite")
_r("pubmatic.com", None, ADVERTISING, "PubMatic")
_r("casalemedia.com", None, ADVERTISING, "Index Exchange")
_r("demdex.net", None, ADVERTISING, "Adobe Audience Manager", COLLECTION)
_r("everesttech.net", None, ADVERTISING, "Adobe Advertising", COLLECTION)
_r("sc-static.net", None, ADVERTISING, "Snap Pixel", LOADER)
_r("tr.snapchat.com", None, ADVERTISING, "Snap Pixel", COLLECTION)
_r("ct.pinterest.com", None, ADVERTISING, "Pinterest Tag", COLLECTION)
_r("s.pinimg.com", r"^/ct/", ADVERTISING, "Pinterest Tag", LOADER)
_r("quantserve.com", None, ADVERTISING, "Quantcast Measure")

# Social widgets / embeds
for _d, _v in [
    ("platform.twitter.com", "Twitter/X"), ("syndication.twitter.com", "Twitter/X"),
    ("platform.linkedin.com", "LinkedIn"), ("youtube.com", "YouTube"),
    ("youtube-nocookie.com", "YouTube (privacy-enhanced)"), ("instagram.com", "Instagram"),
    ("tiktok.com", "TikTok"), ("vimeo.com", "Vimeo"), ("pinterest.com", "Pinterest"),
    ("addthis.com", "AddThis"), ("sharethis.com", "ShareThis"),
]:
    _r(_d, None, SOCIAL, _v, EMBED)

# Fonts
for _d, _v in [
    ("fonts.googleapis.com", "Google Fonts"), ("fonts.gstatic.com", "Google Fonts"),
    ("use.typekit.net", "Adobe Fonts"), ("p.typekit.net", "Adobe Fonts"),
    ("fonts.bunny.net", "Bunny Fonts"), ("use.fontawesome.com", "Font Awesome"),
    ("kit.fontawesome.com", "Font Awesome"), ("ka-f.fontawesome.com", "Font Awesome"),
    ("fast.fonts.net", "Fonts.com"),
]:
    _r(_d, None, FONT, _v, CONTENT)

# Content / CDN
for _d, _v in [
    ("cdnjs.cloudflare.com", "cdnjs"), ("cdn.jsdelivr.net", "jsDelivr"), ("unpkg.com", "unpkg"),
    ("ajax.googleapis.com", "Google Hosted Libraries"), ("code.jquery.com", "jQuery CDN"),
    ("gstatic.com", "Google static content"), ("ytimg.com", "YouTube images"),
    ("akamaized.net", "Akamai"), ("akamaihd.net", "Akamai"), ("cloudfront.net", "Amazon CloudFront"),
    ("azureedge.net", "Azure CDN"), ("fastly.net", "Fastly"), ("cloudflare.com", "Cloudflare"),
    ("bootstrapcdn.com", "BootstrapCDN"), ("maps.googleapis.com", "Google Maps"),
    ("recaptcha.net", "reCAPTCHA"), ("hcaptcha.com", "hCaptcha"),
]:
    _r(_d, None, CONTENT_CDN, _v, CONTENT)

# GA4 hit on any host: /g/collect?...tid=G-...
_GA4_COLLECT_PATH_RE = re.compile(r"/g/collect$", re.IGNORECASE)
_GA4_COLLECT_QUERY_RE = re.compile(r"(^|&)tid=G-", re.IGNORECASE)
# Piano through a site's own domain: /event or /hit.xiti with site id and visitor id.
_PIANO_COLLECT_PATH_RE = re.compile(r"/(event|hit\.xiti)$", re.IGNORECASE)

# Older domain -> name table, built from the rules (still imported elsewhere).
KNOWN_TRACKER_DOMAINS: Dict[str, str] = {
    d: v for d, _p, c, v, _a in _RULES if c in (TAG_MANAGER, ANALYTICS, ADVERTISING)
}


@dataclass
class NetworkRequest:
    url: str
    domain: str
    resource_type: str  # Playwright's request type
    is_third_party: bool
    # Vendor name for any known tracking/tag host. Also set on loaders, so it isn't proof of tracking (see is_tracking).
    tracker_name: Optional[str] = None
    category: str = UNKNOWN
    vendor: Optional[str] = None
    activity: str = CONTENT

    @property
    def is_tracking(self) -> bool:
        """Real tracking: an analytics/advertising collection hit."""
        return self.category in _TRACKING_CATEGORIES and self.activity == COLLECTION

    @property
    def is_observation(self) -> bool:
        """Worth reporting but not tracking (tag managers, loaders, embeds)."""
        return not self.is_tracking and (
            self.category == TAG_MANAGER
            or (self.category in _TRACKING_CATEGORIES and self.activity == LOADER)
            or self.category == SOCIAL
        )

    def short(self) -> str:
        p = urlparse(self.url)
        path = p.path if len(p.path) <= 60 else p.path[:57] + "…"
        return f"{self.domain}{path}"


@dataclass
class PreConsentNetworkResult:
    available: bool = False  # False when the browser couldn't run; that isn't "clean"
    requests: List[NetworkRequest] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def third_party_requests(self) -> List[NetworkRequest]:
        return [r for r in self.requests if r.is_third_party]

    @property
    def tracker_requests(self) -> List[NetworkRequest]:
        """Real tracking hits only."""
        return tracking_requests(self.requests)

    @property
    def vendor_requests(self) -> List[NetworkRequest]:
        """Every request to a known analytics/advertising/tag-manager vendor (loaders included)."""
        return [r for r in self.requests if r.tracker_name]

    def by_category(self) -> Dict[str, List[NetworkRequest]]:
        return group_by_category(self.requests)


def tracking_requests(requests: List[NetworkRequest]) -> List[NetworkRequest]:
    return [r for r in requests if r.is_tracking]


def group_by_category(requests: List[NetworkRequest]) -> Dict[str, List[NetworkRequest]]:
    out: Dict[str, List[NetworkRequest]] = {}
    for r in requests:
        out.setdefault(r.category, []).append(r)
    return out


def summarize_requests(requests: List[NetworkRequest], max_items: int = 8) -> dict:
    """Summary for the report: counts per category and sample vendors/URLs."""
    groups = group_by_category(requests)
    summary: Dict[str, dict] = {}
    for cat, reqs in groups.items():
        vendors = sorted({r.vendor for r in reqs if r.vendor})
        summary[cat] = {
            "label": CATEGORY_LABELS.get(cat, cat),
            "count": len(reqs),
            "vendors": vendors[:max_items],
            "tracking_count": sum(1 for r in reqs if r.is_tracking),
            "samples": [r.short() for r in reqs[:max_items]],
            # The actual collection hits, listed in the report as "Tracking before consent".
            "tracking_samples": [f"{r.vendor or CATEGORY_LABELS.get(cat, cat)}|{r.short()}"
                                 for r in reqs if r.is_tracking][:max_items],
        }
    return summary


async def capture_pre_consent_requests(url: str, settle_ms: int = SETTLE_MS) -> PreConsentNetworkResult:
    """Loads `url` in a fresh, cookie-less browser and records every request. Never clicks the banner."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.info("consent/network.py: playwright not installed — skipping pre-consent capture")
        return PreConsentNetworkResult(available=False, error="playwright not installed")

    hostname = urlparse(url).hostname or ""
    captured: List[NetworkRequest] = []

    try:
        async with async_playwright() as pw:
            browser = await launch_chromium(pw)
            try:
                context = await browser.new_context()
                page = await context.new_page()

                page.on("request", lambda request: captured.append(_classify(request.url, request.resource_type, hostname)))

                await page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
                await page.wait_for_timeout(settle_ms)
            finally:
                await browser.close()

        return PreConsentNetworkResult(available=True, requests=captured)

    except Exception as exc:  # noqa: BLE001 — a failed capture should never break the audit
        logger.warning(f"consent/network.py: failed to capture {url}: {exc}")
        return PreConsentNetworkResult(available=False, error=str(exc))


def _registrable(host: str) -> str:
    """Rough main domain (handles co.uk, com.au, co.in)."""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "gov", "ac", "edu", "gouv"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _is_first_party(domain: str, first_party_hostname: str) -> bool:
    if not domain or not first_party_hostname:
        return False
    fp = first_party_hostname.lower()
    if fp.startswith("www."):
        fp = fp[4:]
    return domain == fp or domain.endswith("." + fp) or _registrable(domain) == _registrable(fp)


def _domain_matches(domain: str, suffix: str) -> bool:
    return domain == suffix or domain.endswith("." + suffix)


def _classify(request_url: str, resource_type: str, first_party_hostname: str) -> NetworkRequest:
    parsed = urlparse(request_url)
    domain = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    rtype = (resource_type or "").lower()
    third_party = bool(domain) and not _is_first_party(domain, first_party_hostname)

    category, vendor, activity = None, None, None
    for suffix, path_re, cat, ven, act in _RULES:
        if not _domain_matches(domain, suffix):
            continue
        if path_re is not None and not path_re.search(path):
            continue
        category, vendor, activity = cat, ven, act
        break

    if category is None:
        if _GA4_COLLECT_PATH_RE.search(path) and _GA4_COLLECT_QUERY_RE.search(parsed.query or ""):
            # Server-side GA4 still sends a GA4 hit.
            category, vendor, activity = ANALYTICS, "Google Analytics", COLLECTION
        elif _PIANO_COLLECT_PATH_RE.search(path) and re.search(r"(^|&)s=\d+(&|$)", parsed.query or "") \
                and "idclient=" in (parsed.query or ""):
            category, vendor, activity = ANALYTICS, "Piano Analytics", COLLECTION
        elif not domain:
            category, activity = UNKNOWN, CONTENT
        elif not third_party:
            category, activity = FIRST_PARTY, CONTENT
        elif rtype == "font":
            category, activity = FONT, CONTENT
        else:
            category, activity = OTHER_THIRD_PARTY, CONTENT

    if activity is None:
        # Known vendor without a path rule: script/stylesheet = loader; anything else = collection hit.
        activity = LOADER if rtype in _LOADER_RESOURCE_TYPES else COLLECTION

    tracker_name = vendor if category in (ANALYTICS, ADVERTISING, TAG_MANAGER) else None

    return NetworkRequest(
        url=request_url, domain=domain, resource_type=resource_type,
        is_third_party=third_party, tracker_name=tracker_name,
        category=category, vendor=vendor, activity=activity,
    )


def classify_request(request_url: str, resource_type: str = "other", first_party_hostname: str = "") -> NetworkRequest:
    """Classifies one request URL."""
    return _classify(request_url, resource_type, first_party_hostname)


def _names(reqs: List[NetworkRequest]) -> List[str]:
    return sorted({r.vendor or r.domain for r in reqs})


def check_pre_consent_network(result: PreConsentNetworkResult) -> List[dict]:
    """Findings from the captured requests. Nothing when the capture didn't run.
    Only real collection hits give the critical "Tracking before consent"
    finding; loaders and tag managers are observations.
    """
    if not result.available:
        return []

    findings: List[dict] = []
    reqs = result.requests

    tracking = [r for r in reqs if r.is_tracking]
    if tracking:
        names = _names(tracking)
        samples = sorted({r.short() for r in tracking})[:5]
        findings.append({
            "module": "consent",
            "category": "network",
            "severity": "critical",
            "title": "Tracking activity before consent",
            "description": f"{len(tracking)} analytics/advertising data-collection request(s) "
                            f"({', '.join(names)}) were observed before any consent action was taken. "
                            f"Examples: {', '.join(samples)}.",
            "recommendation": "Hold these vendors' collection back until the visitor has consented — "
                               "e.g. configure tags to fire only after the CMP's consent update / "
                               "Consent Mode 'granted' signal.",
        })

    tracking_vendors = {r.vendor for r in tracking}

    tag_managers = [r for r in reqs if r.category == TAG_MANAGER]
    if tag_managers:
        names = _names(tag_managers)
        downstream = (
            f"Downstream collection was observed from: {', '.join(sorted(tracking_vendors))}."
            if tracking_vendors else
            "No downstream analytics/advertising collection request was observed before consent."
        )
        findings.append({
            "module": "consent",
            "category": "network",
            "severity": "info",
            "title": "Observation: tag manager loaded before consent",
            "description": f"{', '.join(names)} loaded before consent. Loading a tag container is not "
                            f"by itself tracking — what matters is which tags it fires. {downstream}",
            "recommendation": "Make sure tags inside the container are gated on consent (e.g. GTM "
                               "Consent Mode / consent-initialization triggers).",
        })

    loaders = [r for r in reqs if r.category in _TRACKING_CATEGORIES and r.activity == LOADER
               and r.vendor not in tracking_vendors]
    if loaders:
        findings.append({
            "module": "consent",
            "category": "network",
            "severity": "info",
            "title": "Observation: vendor libraries loaded before consent (no collection observed)",
            "description": f"Libraries from {', '.join(_names(loaders))} were downloaded before consent, "
                            "but no data-collection request from these vendors was observed.",
            "recommendation": "Consider deferring these libraries until consent; downloading them "
                               "still exposes the visitor's IP address to the vendor.",
        })

    social = [r for r in reqs if r.category == SOCIAL]
    if social:
        findings.append({
            "module": "consent",
            "category": "network",
            "severity": "warning",
            "title": "Social embeds load before consent",
            "description": f"Content from {', '.join(_names(social))} loaded before consent. Social "
                            "widgets/embeds can set cookies and profile visitors.",
            "recommendation": "Use click-to-load placeholders or privacy-enhanced embed modes until "
                               "the visitor consents.",
        })

    other = [r for r in reqs if r.category == OTHER_THIRD_PARTY]
    if other:
        domains = sorted({r.domain for r in other})[:5]
        findings.append({
            "module": "consent",
            "category": "network",
            "severity": "info",
            "title": "Unclassified third-party requests before consent",
            "description": f"{len(other)} request(s) to unrecognized third-party domain(s) "
                            f"({', '.join(domains)}) fired before consent. They are not counted as "
                            "tracking without further evidence.",
            "recommendation": "Review whether these requests set cookies or transmit "
                               "personal data, and gate them behind consent if so.",
        })

    return findings
