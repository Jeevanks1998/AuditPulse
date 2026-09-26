"""
consent/region_detector.py

Dedicated region-detection module. Region detection used to be implicit
(or entirely absent) inside consent/consent_score.py, which mixed "which
regional framework applies here" with "how well does the site meet it" —
two different jobs. This module owns only the first one:

    URL + page
        |
        v
    Region Detection  (this module)
        |
        v
    "France" / "California" / "Unknown" ...
        |
        v
    Applicable framework  (consent.consent_score.resolve_applicable_frameworks)
        |
        v
    Consent Audit  (consent.consent_score.build_gdpr_assessment /
                    build_ccpa_assessment, gated by that framework)
        |
        v
    GDPR / UK GDPR / Swiss FADP / CCPA Result

Nothing here scores compliance or grades anything — it only looks at
signals already available from one already-fetched, already-parsed page
(crawler.parser.ParsedPage) plus the page's URL, and reports its best
guess at the audited site's region, with its reasoning and a confidence
level attached. consent_score's `resolve_applicable_frameworks` is
reused (not duplicated) purely to translate the detected region into the
matching framework label ("GDPR" / "UK GDPR" / "Swiss FADP" /
"CCPA/CPRA") for display — that single mapping table is scoring's source
of truth, not this module's.

Detection combines multiple independent signals instead of trusting the
domain alone, since any one of them can be missing, wrong, or generic:

  - domain / subdomain (ccTLD, locale subdomain prefix)
  - hreflang / alternate-URL <link> tags (self-referencing hreflang is
    the strongest of these — it's the page declaring its own locale)
  - <html lang="...">
  - canonical URL's locale path segment
  - the audited URL's own locale path segment (/fr/, /de-de/, /en-gb/)
  - a URL path or on-page name mentioning a region outright
    ("/store/california/", "European Economic Area")
  - a country/region/locale <select> with a pre-selected option
  - consent-platform (CMP) script configuration referencing a country
  - privacy-policy / on-page text referencing a specific regulation
    (GDPR, UK GDPR, Swiss FADP, CCPA/CPRA) by name

Each signal is weighted (strong/medium/weak) by how directly it points
at a specific region; signals are combined per candidate region, and the
region with the most corroborated weight wins. An audit with no signals
at all — or only weak, disagreeing ones — reports REGION_UNKNOWN with
"none"/"low" confidence rather than guessing, since consent_score
already treats unknown as "no verdict", never a failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from crawler.parser import ParsedPage

from consent.consent_score import (
    REGION_EU,
    REGION_SWITZERLAND,
    REGION_UK,
    REGION_UNKNOWN,
    REGION_US_CALIFORNIA,
    REGION_US_OTHER,
    resolve_applicable_frameworks,
)

MODULE = "consent"
CATEGORY = "region"

__all__ = [
    "RegionSignal",
    "RegionDetectionResult",
    "detect_region",
]

# Signal strength tiers. "Strong" = this signal alone is close to
# conclusive (a self-referencing hreflang tag, a ccTLD); "medium" = a
# reasonable, commonly-reliable indicator on its own (html lang with a
# region subtag, a locale path segment); "weak" = suggestive only,
# needs corroboration (a bare language code, a CMP config guess).
SIGNAL_STRONG = 3
SIGNAL_MEDIUM = 2
SIGNAL_WEAK = 1

# ---------------------------------------------------------------------
# Country / region reference tables
# ---------------------------------------------------------------------

# 2-letter ISO country code -> (display name, REGION_* bucket this
# module feeds into consent_score.resolve_applicable_frameworks).
# "EU" bucket also covers EEA members (Norway, Iceland, Liechtenstein) —
# consent_score treats EU and EEA identically (both -> GDPR).
# California is deliberately NOT keyed here by its 2-letter postal code
# ("CA" is also Canada's ISO country code) — it's only ever matched by
# its full name via _FULL_NAME_REGIONS, never a bare 2-letter code.
_COUNTRY_CODE_TABLE: Dict[str, Tuple[str, str]] = {
    "FR": ("France", REGION_EU),
    "DE": ("Germany", REGION_EU),
    "IT": ("Italy", REGION_EU),
    "ES": ("Spain", REGION_EU),
    "BE": ("Belgium", REGION_EU),
    "IE": ("Ireland", REGION_EU),
    "NL": ("Netherlands", REGION_EU),
    "SE": ("Sweden", REGION_EU),
    "NO": ("Norway", REGION_EU),
    "DK": ("Denmark", REGION_EU),
    "FI": ("Finland", REGION_EU),
    "AT": ("Austria", REGION_EU),
    "PT": ("Portugal", REGION_EU),
    "PL": ("Poland", REGION_EU),
    "CZ": ("Czechia", REGION_EU),
    "RO": ("Romania", REGION_EU),
    "BG": ("Bulgaria", REGION_EU),
    "HR": ("Croatia", REGION_EU),
    "CY": ("Cyprus", REGION_EU),
    "EE": ("Estonia", REGION_EU),
    "GR": ("Greece", REGION_EU),
    "HU": ("Hungary", REGION_EU),
    "LV": ("Latvia", REGION_EU),
    "LT": ("Lithuania", REGION_EU),
    "LU": ("Luxembourg", REGION_EU),
    "MT": ("Malta", REGION_EU),
    "SK": ("Slovakia", REGION_EU),
    "SI": ("Slovenia", REGION_EU),
    "IS": ("Iceland", REGION_EU),
    "LI": ("Liechtenstein", REGION_EU),
    "GB": ("United Kingdom", REGION_UK),
    "UK": ("United Kingdom", REGION_UK),
    "CH": ("Switzerland", REGION_SWITZERLAND),
    "US": ("United States", REGION_US_OTHER),
}

# Bare language code (no region subtag) -> the country code it's
# defaulted to for our purposes, used only as a weak fallback when
# nothing more specific (a region subtag, a ccTLD) is available.
_LANGUAGE_ONLY_FALLBACK: Dict[str, str] = {
    "FR": "FR", "DE": "DE", "IT": "IT", "ES": "ES", "NL": "NL", "PT": "PT",
    "SV": "SE", "DA": "DK", "FI": "FI", "PL": "PL", "CS": "CZ", "RO": "RO",
    "EL": "GR", "HU": "HU", "GA": "IE",
    "UK": "UK", "GB": "GB",  # path/subdomain segments only, not real ISO 639 codes
}

# Full display names matched as whole words/phrases in URL paths, page
# text, and pre-selected <select> options — the only place California
# (and the generic EU/EEA labels) are recognized, since none of them has
# an unambiguous 2-letter code of their own.
_FULL_NAME_REGIONS: Dict[str, str] = {name: region for name, region in _COUNTRY_CODE_TABLE.values()}
_FULL_NAME_REGIONS.update({
    "California": REGION_US_CALIFORNIA,
    "European Union": REGION_EU,
    "European Economic Area": REGION_EU,
})

_BUCKET_DEFAULT_LABEL: Dict[str, str] = {
    REGION_EU: "European Union",
    REGION_UK: "United Kingdom",
    REGION_SWITZERLAND: "Switzerland",
    REGION_US_CALIFORNIA: "California",
    REGION_US_OTHER: "United States",
    REGION_UNKNOWN: "Unknown",
}

_SOURCE_DISPLAY_NAMES: Dict[str, str] = {
    "domain_tld": "Domain",
    "subdomain": "Subdomain",
    "hreflang": "hreflang",
    "html_lang": "HTML lang attribute",
    "canonical_url": "Canonical URL",
    "url_locale_path": "URL locale path",
    "geographic_path": "URL path",
    "country_selector": "Country/language selector",
    "consent_platform_config": "Consent platform configuration",
    "privacy_policy_text": "Privacy policy / site text",
}


@dataclass
class RegionSignal:
    """One piece of evidence pointing at a region. `country` is the
    specific display name this particular signal points at (e.g.
    "France"); it can differ in specificity from the final `region`
    bucket it maps onto (e.g. a generic "GDPR" text mention has
    country=None-ish but still maps to the REGION_EU bucket)."""
    source: str    # machine key — see _SOURCE_DISPLAY_NAMES for display form
    region: str    # REGION_* bucket this signal supports
    country: str   # specific display name backing this signal
    weight: int
    detail: str    # human-readable explanation, used in the final `reason`


@dataclass
class RegionDetectionResult:
    region: str                          # REGION_* bucket — pass straight into
                                          # consent_score.resolve_applicable_frameworks /
                                          # build_consent_summary(region=...)
    region_label: str                    # human display, e.g. "France", "California", "Unknown"
    framework: Optional[str]             # "GDPR" / "UK GDPR" / "Swiss FADP" / "CCPA/CPRA" / None
    confidence: str                      # "high" | "medium" | "low" | "none"
    source: str                          # e.g. "Domain + hreflang"
    reason: str                          # synthesized explanation from the winning signals
    signals: List[RegionSignal] = field(default_factory=list)  # every signal collected, not just the winner's


def _normalize_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.netloc.lower()}{p.path.rstrip('/')}"


def _parse_locale_country(code: str) -> Optional[str]:
    """"fr-FR" -> "FR"; "en-GB" -> "GB"; "fr" -> "FR" (fallback); "xx" (unrecognized) -> None."""
    code = (code or "").strip()
    if not code:
        return None
    parts = re.split(r"[-_]", code)
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isalpha():
        return parts[-1].upper()
    return _LANGUAGE_ONLY_FALLBACK.get(parts[0].upper())


_PATH_LOCALE_RE = re.compile(r"^/([a-z]{2})(?:[-_]([a-z]{2}))?(?:/|$)", re.IGNORECASE)


def _locale_code_from_path(path: str) -> Optional[str]:
    if not path:
        return None
    m = _PATH_LOCALE_RE.match(path)
    if not m:
        return None
    lang, region = m.group(1), m.group(2)
    if region:
        return region.upper()
    return _LANGUAGE_ONLY_FALLBACK.get(lang.upper())


# ---------------------------------------------------------------------
# Individual signal detectors — each reads one source and returns
# whatever it found (or None / [] when it found nothing usable). None
# of these guess; an inconclusive read is simply left out rather than
# forced into a low-confidence guess.
# ---------------------------------------------------------------------

def _detect_from_domain(url: str) -> Optional[RegionSignal]:
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    if not host:
        return None
    if host.endswith(".co.uk") or host.endswith(".uk"):
        name, region = _COUNTRY_CODE_TABLE["UK"]
        return RegionSignal(
            "domain_tld", region, name, SIGNAL_STRONG,
            "Domain uses the .uk / .co.uk country-code TLD, used for the United Kingdom.",
        )
    tld = host.rsplit(".", 1)[-1].upper()
    hit = _COUNTRY_CODE_TABLE.get(tld)
    if not hit:
        return None
    name, region = hit
    # .us alone says "United States" but nothing state-specific, so it's
    # treated as weaker evidence than a genuinely EU/UK/CH ccTLD.
    weight = SIGNAL_MEDIUM if tld == "US" else SIGNAL_STRONG
    return RegionSignal(
        "domain_tld", region, name, weight,
        f"Domain uses the .{tld.lower()} country-code TLD, associated with {name}.",
    )


def _detect_from_subdomain(url: str) -> Optional[RegionSignal]:
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    labels = host.split(".")
    if len(labels) < 3:
        return None
    sub = labels[0]
    if sub in ("www", "m", "amp", "app", "api", "cdn"):
        return None
    code = sub.upper() if len(sub) == 2 else _LANGUAGE_ONLY_FALLBACK.get(sub.split("-")[0].upper())
    hit = _COUNTRY_CODE_TABLE.get(code) if code else None
    if not hit:
        return None
    name, region = hit
    return RegionSignal(
        "subdomain", region, name, SIGNAL_MEDIUM,
        f'Subdomain "{sub}" is a locale/country prefix associated with {name}.',
    )


def _detect_from_hreflang(page: ParsedPage, url: str) -> List[RegionSignal]:
    """
    Reads <link rel="alternate" hreflang="..."> tags. A tag whose href
    points back at this same page (a "self-referencing" hreflang — the
    normal way a site declares "this URL IS the French version") is a
    strong, direct signal. Any other alternate-locale link just proves
    the site supports multiple locales, not which one this page is, so
    it's kept as weak, corroborating-only evidence.
    """
    signals: List[RegionSignal] = []
    self_norm = _normalize_url(url)
    for tag in page.soup.find_all("link"):
        rel = tag.get("rel") or []
        rel = [rel] if isinstance(rel, str) else rel
        if not any(r.lower() == "alternate" for r in rel):
            continue
        hreflang = (tag.get("hreflang") or "").strip()
        href = tag.get("href")
        if not hreflang or hreflang.lower() == "x-default" or not href:
            continue
        code = _parse_locale_country(hreflang)
        hit = _COUNTRY_CODE_TABLE.get(code) if code else None
        if not hit:
            continue
        name, region = hit
        is_self = _normalize_url(href) == self_norm
        weight = SIGNAL_STRONG if is_self else SIGNAL_WEAK
        detail = (
            f'This page self-references hreflang="{hreflang}", associated with {name}.' if is_self
            else f'Page offers an alternate hreflang="{hreflang}" version for {name}.'
        )
        signals.append(RegionSignal("hreflang", region, name, weight, detail))
    return signals


def _detect_from_html_lang(page: ParsedPage) -> Optional[RegionSignal]:
    lang = (page.lang or "").strip()
    if not lang:
        return None
    parts = re.split(r"[-_]", lang)
    if len(parts) >= 2 and len(parts[-1]) == 2 and parts[-1].isalpha():
        code, weight = parts[-1].upper(), SIGNAL_MEDIUM
    else:
        code, weight = _LANGUAGE_ONLY_FALLBACK.get(parts[0].upper()), SIGNAL_WEAK
    hit = _COUNTRY_CODE_TABLE.get(code) if code else None
    if not hit:
        return None
    name, region = hit
    return RegionSignal(
        "html_lang", region, name, weight,
        f'The page declares <html lang="{lang}">, associated with {name}.',
    )


def _detect_from_canonical(page: ParsedPage) -> Optional[RegionSignal]:
    if not page.canonical:
        return None
    code = _locale_code_from_path(urlparse(page.canonical).path)
    hit = _COUNTRY_CODE_TABLE.get(code) if code else None
    if not hit:
        return None
    name, region = hit
    return RegionSignal(
        "canonical_url", region, name, SIGNAL_MEDIUM,
        f'Canonical URL has a "{code.lower()}" locale path segment, associated with {name}.',
    )


def _detect_from_url_path(url: str) -> Optional[RegionSignal]:
    code = _locale_code_from_path(urlparse(url).path)
    hit = _COUNTRY_CODE_TABLE.get(code) if code else None
    if not hit:
        return None
    name, region = hit
    return RegionSignal(
        "url_locale_path", region, name, SIGNAL_MEDIUM,
        f'Audited URL has a "{code.lower()}" locale path segment, associated with {name}.',
    )


def _detect_from_geographic_path_names(url: str) -> Optional[RegionSignal]:
    """Catches paths that spell a region out by name rather than by
    code, e.g. "/store/california/" or "/eu/european-union-shipping/"."""
    path = (urlparse(url).path or "").replace("-", " ").replace("_", " ").lower()
    if not path:
        return None
    for name, region in _FULL_NAME_REGIONS.items():
        if re.search(rf"\b{re.escape(name.lower())}\b", path):
            return RegionSignal(
                "geographic_path", region, name, SIGNAL_MEDIUM,
                f'URL path contains "{name}".',
            )
    return None


_SELECTOR_KEYWORDS = ("country", "region", "locale", "market")


def _detect_from_selector(page: ParsedPage) -> Optional[RegionSignal]:
    """Looks for a country/region <select> with a pre-selected option
    naming a recognized region — an unselected list of every country a
    multi-country site supports isn't itself evidence of the current
    one, so only a `selected` option counts. Treated as strong evidence:
    a deliberately pre-selected value is about as declarative as a site
    gets short of stating its region outright."""
    for select in page.soup.find_all("select"):
        attrs_blob = " ".join(str(select.get(a, "")) for a in ("id", "name", "class")).lower()
        if not any(k in attrs_blob for k in _SELECTOR_KEYWORDS):
            continue
        for option in select.find_all("option"):
            if option.get("selected") is None:
                continue
            text = (option.get_text(strip=True) or "").strip()
            region = _FULL_NAME_REGIONS.get(text)
            if region:
                return RegionSignal(
                    "country_selector", region, text, SIGNAL_STRONG,
                    f'A country/region selector\'s pre-selected option is "{text}".',
                )
    return None


_CMP_GEO_RE = re.compile(r'"country"\s*:\s*"([a-z]{2})"|[?&](?:geo|country)=([a-z]{2})\b', re.IGNORECASE)


def _detect_from_consent_platform_config(page: ParsedPage) -> Optional[RegionSignal]:
    """Best-effort read of a CMP's own script src/config for a country
    hint (e.g. a OneTrust/CMP loader called with `?geo=de` or an inline
    config block with `"country":"de"`) — weak on its own since these
    are frequently defaults rather than detected geography, but useful
    corroboration alongside a stronger signal."""
    for tag in page.soup.find_all("script"):
        blob = f'{tag.get("src") or ""} {tag.string or tag.get_text() or ""}'
        m = _CMP_GEO_RE.search(blob)
        if not m:
            continue
        code = (m.group(1) or m.group(2) or "").upper()
        hit = _COUNTRY_CODE_TABLE.get(code)
        if not hit:
            continue
        name, region = hit
        return RegionSignal(
            "consent_platform_config", region, name, SIGNAL_WEAK,
            f'The page\'s consent-management script configuration references country code "{code}" ({name}).',
        )
    return None


# Regulation-name mentions in the page's own visible text (privacy
# policy pages themselves aren't fetched here — this reads whatever
# page was passed in, typically the homepage — but sites very commonly
# name-check their applicable regulation in a footer/banner blurb).
# Naming a *specific* statute (CCPA/CPRA, UK GDPR, Swiss FADP) is quite
# unambiguous, so those are weighted strong — strong enough to outrank
# generic "en-US"/"US" locale boilerplate that carries no real regional
# certainty. The bare "GDPR" mention is deliberately weak instead: it's
# common on sites that merely advertise compliance without actually
# being EU-established/targeted.
_REGULATION_TEXT_SIGNALS: Tuple[Tuple["re.Pattern[str]", str, str, int], ...] = (
    (
        re.compile(r"california consumer privacy act|\bcpra\b|\bccpa\b|california residents", re.IGNORECASE),
        REGION_US_CALIFORNIA, "California", SIGNAL_STRONG,
    ),
    (
        re.compile(r"\buk gdpr\b|data protection act 2018", re.IGNORECASE),
        REGION_UK, "United Kingdom", SIGNAL_STRONG,
    ),
    (
        re.compile(r"swiss federal act on data protection|\bfadp\b", re.IGNORECASE),
        REGION_SWITZERLAND, "Switzerland", SIGNAL_STRONG,
    ),
    (
        re.compile(r"general data protection regulation|\bgdpr\b|european economic area|\beea\b", re.IGNORECASE),
        REGION_EU, "European Union", SIGNAL_WEAK,
    ),
)


def _detect_from_privacy_policy_text(page: ParsedPage) -> List[RegionSignal]:
    text = page.text_content or ""
    signals: List[RegionSignal] = []
    for pattern, region, name, weight in _REGULATION_TEXT_SIGNALS:
        if pattern.search(text):
            signals.append(RegionSignal(
                "privacy_policy_text", region, name, weight,
                f"Page text uses {name}-specific privacy-regulation language.",
            ))
    return signals


# ---------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------

def detect_region(page: ParsedPage, url: Optional[str] = None) -> RegionDetectionResult:
    """
    Runs every signal detector above once and combines the results into
    a single best-guess region, its matching regulatory framework, and
    a confidence level — the only entry point callers need.

    `url` defaults to `page.url`; pass it explicitly if the URL you want
    judged (e.g. the originally-requested URL before redirects) differs
    from where the page ended up.
    """
    target_url = url or page.url
    signals: List[RegionSignal] = []

    for one in (_detect_from_domain(target_url), _detect_from_subdomain(target_url)):
        if one:
            signals.append(one)
    signals += _detect_from_hreflang(page, target_url)
    for one in (
        _detect_from_html_lang(page),
        _detect_from_canonical(page),
        _detect_from_url_path(target_url),
        _detect_from_geographic_path_names(target_url),
        _detect_from_selector(page),
        _detect_from_consent_platform_config(page),
    ):
        if one:
            signals.append(one)
    signals += _detect_from_privacy_policy_text(page)

    if not signals:
        return RegionDetectionResult(
            region=REGION_UNKNOWN,
            region_label=_BUCKET_DEFAULT_LABEL[REGION_UNKNOWN],
            framework=None,
            confidence="none",
            source="None",
            reason="No region signals (domain, hreflang, lang, locale path, selectors, CMP config, "
                   "or on-page regulatory text) were found for this page.",
            signals=[],
        )

    bucket_weight: Dict[str, int] = {}
    country_weight: Dict[Tuple[str, str], int] = {}
    for sig in signals:
        bucket_weight[sig.region] = bucket_weight.get(sig.region, 0) + sig.weight
        key = (sig.region, sig.country)
        country_weight[key] = country_weight.get(key, 0) + sig.weight

    winner_region = max(
        bucket_weight,
        key=lambda r: (bucket_weight[r], max(s.weight for s in signals if s.region == r)),
    )
    winner_weight = bucket_weight[winner_region]
    winner_signals = [s for s in signals if s.region == winner_region]
    winner_signals.sort(key=lambda s: -s.weight)
    distinct_sources = {s.source for s in winner_signals}

    # Most-corroborated specific country/name within the winning bucket
    # (e.g. "France" beats "Germany" if both were seen but France had
    # more/stronger signals); falls back to the bucket's generic label
    # when nothing more specific was found (e.g. a lone "GDPR" mention).
    candidates = {c: w for (r, c), w in country_weight.items() if r == winner_region}
    region_label = max(candidates, key=lambda c: candidates[c]) if candidates \
        else _BUCKET_DEFAULT_LABEL.get(winner_region, winner_region)

    if winner_weight >= 5 and len(distinct_sources) >= 2:
        confidence = "high"
    elif winner_weight >= 3 or (winner_weight >= 2 and len(distinct_sources) >= 2):
        confidence = "medium"
    elif winner_weight >= 1:
        confidence = "low"
    else:  # pragma: no cover — unreachable given signals is non-empty, kept as a safe fallback
        confidence = "none"

    seen_labels: List[str] = []
    for s in winner_signals:
        label = _SOURCE_DISPLAY_NAMES.get(s.source, s.source)
        if label not in seen_labels:
            seen_labels.append(label)
    source_label = " + ".join(seen_labels)

    reason = "; ".join(dict.fromkeys(s.detail for s in winner_signals))

    frameworks = resolve_applicable_frameworks(winner_region)
    if frameworks.assess_gdpr:
        framework = frameworks.gdpr_framework_name
    elif frameworks.assess_ccpa:
        framework = "CCPA/CPRA"
    else:
        framework = None

    return RegionDetectionResult(
        region=winner_region,
        region_label=region_label,
        framework=framework,
        confidence=confidence,
        source=source_label,
        reason=reason,
        signals=signals,
    )
