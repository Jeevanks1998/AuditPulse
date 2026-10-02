"""
consent/region.py

The central region engine. Decides *where* a site is aimed and therefore
*which* regional privacy frameworks an audit may assess — before any
assessment runs:

    Region detected
           ↓
    Applicable frameworks
           ↓
    consent_score builds the applicable assessment(s) only

Output (RegionResult):

    region                 e.g. "IN" / "EU" / "UK" / "US-CA" / "UNKNOWN"
    confidence             high | medium | low
    evidence               human-readable list, e.g. [".in domain",
                           "India-specific privacy text", "India localisation",
                           "CMP regional configuration"]
    applicable_frameworks  e.g. ["dpdp"]  (["gdpr"], ["ccpa"], or [] )
    applicability_status   "determined" | "not_determined"

Mapping:

    India          → DPDP (Digital Personal Data Protection Act, 2023)
    EU/EEA         → GDPR + ePrivacy
    United Kingdom → UK GDPR + PECR (assessed with the GDPR checks)
    California     → CCPA/CPRA (a *candidate*: the law's thresholds depend
                     on the business, which a website scan can't see)
    Unknown        → framework not determined; technical consent scan only;
                     regional compliance = "Not assessed"

Detection is evidence-based and conservative: each signal adds a weighted
vote for a region, and a region is only selected when its total reaches
DECISION_THRESHOLD. A country-code TLD alone qualifies; one weak hint such
as lang="en-US" does not. An explicit `target_region` always wins.

Signals come from two passes:
  1. `detect_region` — before anything else in the pipeline: URL, page
     language, and the page's own text (step 1 of consent.analyze_site).
  2. `refine_region` — after the live browser pass: what the *rendered*
     consent banner says (e.g. "Do Not Sell or Share", "DPDP", "GDPR"),
     i.e. how the CMP was regionally configured for this visit.

consent/ccpa.py, consent/consent_score.py and the rest of consent/ never
decide applicability themselves — they only detect technical signals or
build assessments for the frameworks this module returns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse

from crawler.parser import ParsedPage

# ---- regions ----------------------------------------------------------------
REGION_IN = "IN"
REGION_EU = "EU"
REGION_UK = "UK"
REGION_US_CA = "US-CA"
REGION_UNKNOWN = "UNKNOWN"

REGION_LABELS = {
    REGION_IN: "India",
    REGION_EU: "EU / EEA",
    REGION_UK: "United Kingdom",
    REGION_US_CA: "United States — California candidate",
    REGION_UNKNOWN: "Unknown",
}

# ---- frameworks ---------------------------------------------------------------
FW_GDPR = "gdpr"
FW_CCPA = "ccpa"
FW_DPDP = "dpdp"

FRAMEWORK_LABELS = {
    FW_GDPR: "GDPR + ePrivacy",
    FW_CCPA: "CCPA / CPRA",
    FW_DPDP: "India DPDP Act 2023",
}

REGION_FRAMEWORKS = {
    REGION_IN: [FW_DPDP],
    REGION_EU: [FW_GDPR],
    REGION_UK: [FW_GDPR],
    REGION_US_CA: [FW_CCPA],
}

STATUS_DETERMINED = "determined"
STATUS_NOT_DETERMINED = "not_determined"

DECISION_THRESHOLD = 50
HIGH_CONFIDENCE = 80

_EU_EEA_TLDS = {
    "at", "be", "bg", "hr", "cy", "cz", "dk", "ee", "fi", "fr", "de", "gr", "hu", "ie", "it",
    "lv", "lt", "lu", "mt", "nl", "pl", "pt", "ro", "sk", "si", "es", "se", "eu",
    "is", "li", "no",  # EEA
}
_EU_LANGS = {
    "bg", "hr", "cs", "da", "nl", "et", "fi", "fr", "de", "el", "hu", "ga", "it", "lv", "lt",
    "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "is", "no", "nb", "nn",
}
_INDIAN_LANGS = {"hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "pa", "or", "as", "ur"}

# EU country path/subdomain segments on otherwise global domains
# (e.g. axa.com/fr/, de.example.com) — "EU country URL".
_EU_URL_SEGMENTS = _EU_EEA_TLDS - {"eu", "is", "li", "no"}

_REGION_ALIASES = {
    "in": REGION_IN, "india": REGION_IN,
    "eu": REGION_EU, "eea": REGION_EU, "europe": REGION_EU,
    "uk": REGION_UK, "gb": REGION_UK, "united kingdom": REGION_UK,
    "us-ca": REGION_US_CA, "ca-us": REGION_US_CA, "california": REGION_US_CA, "us": REGION_US_CA,
}

# (regex, region, weight, evidence text)
_TEXT_SIGNALS = [
    # California / US
    (re.compile(r"\bdo not sell (?:or share )?my (?:personal )?(?:information|data|info)\b", re.I),
     REGION_US_CA, 35, "“Do Not Sell or Share” wording"),
    (re.compile(r"\byour privacy choices\b", re.I), REGION_US_CA, 25, "“Your Privacy Choices” wording"),
    (re.compile(r"\bcalifornia (?:consumer )?privacy (?:act|rights|notice)\b|\bCCPA\b|\bCPRA\b", re.I),
     REGION_US_CA, 30, "California privacy law referenced"),
    (re.compile(r"\b(?:CA|California)\s+9[0-6]\d{3}\b"), REGION_US_CA, 25, "California street address"),
    # India
    (re.compile(r"\bGSTIN\b|\bCIN\s*[:\-]?\s*[LU]\d{5}", re.I), REGION_IN, 35, "Indian company identifiers (GSTIN/CIN)"),
    (re.compile(r"\b(?:Pvt\.?\s*Ltd|Private Limited)\b", re.I), REGION_IN, 25, "Indian company form (Pvt. Ltd.)"),
    (re.compile(r"₹|\bINR\b|\bRs\.\s?\d"), REGION_IN, 20, "India localisation (rupee prices)"),
    (re.compile(r"\+91[\s-]?\d{2,5}[\s-]?\d{3,}"), REGION_IN, 20, "India localisation (+91 phone number)"),
    (re.compile(r"\bDPDP\b|Digital Personal Data Protection", re.I), REGION_IN, 30, "India-specific privacy text (DPDP Act)"),
    (re.compile(r"\bGrievance Officer\b|\bData Protection Board of India\b|\bConsent Manager\b.*\bIndia\b", re.I),
     REGION_IN, 30, "India-specific privacy text (Grievance Officer / Data Protection Board)"),
    # EU / EEA
    (re.compile(r"\bGDPR\b|General Data Protection Regulation|\bDSGVO\b|\bRGPD\b", re.I),
     REGION_EU, 25, "GDPR reference"),
    (re.compile(r"\bright to (?:erasure|be forgotten|data portability)\b|\blegitimate interests?\b"
                r"|\bdata protection officer\b|\bsupervisory authority\b", re.I),
     REGION_EU, 15, "EU privacy language"),
    (re.compile(r"\bImpressum\b"), REGION_EU, 35, "German “Impressum” legal notice"),
    (re.compile(r"\bmentions l[ée]gales\b", re.I), REGION_EU, 30, "French “Mentions légales”"),
    (re.compile(r"\b(?:GmbH|S\.A\.S\.|S\.r\.l\.|B\.V\.)\b"), REGION_EU, 20, "EU company form"),
    (re.compile(r"€\s?\d|\d\s?€|\bEUR\b"), REGION_EU, 15, "Euro prices"),
    # UK
    (re.compile(r"\bCompanies House\b|\bregistered in England(?: and Wales)?\b", re.I), REGION_UK, 35, "UK company registration"),
    (re.compile(r"£\s?\d"), REGION_UK, 15, "Pound sterling prices"),
    (re.compile(r"\bInformation Commissioner|\bUK GDPR\b|\bPECR\b", re.I), REGION_UK, 25, "UK privacy law referenced"),
]

# What the *rendered* consent banner says about how the CMP was configured
# for this visit — "CMP regional configuration".
_CMP_SIGNALS = [
    (re.compile(r"\bdo not sell|\bopt[- ]out of (?:the )?sale|your privacy choices|\bCCPA\b|\bCPRA\b", re.I),
     REGION_US_CA, 30, "CMP regional configuration: US opt-out (CCPA-style) banner"),
    (re.compile(r"\bDPDP\b|Digital Personal Data Protection|\bConsent Manager\b", re.I),
     REGION_IN, 30, "CMP regional configuration: India DPDP consent notice"),
    (re.compile(r"\bGDPR\b|\blegitimate interest|\bIAB\b.*\bTCF\b|\bTransparency (?:and|&) Consent Framework", re.I),
     REGION_EU, 25, "CMP regional configuration: GDPR / IAB TCF consent banner"),
]


@dataclass
class RegionSignal:
    region: str
    weight: int
    source: str       # "explicit" | "tld" | "url" | "lang" | "content" | "cmp"
    detail: str

    def as_dict(self) -> dict:
        return {"region": self.region, "weight": self.weight, "source": self.source, "detail": self.detail}


@dataclass
class RegionResult:
    regions: List[str] = field(default_factory=list)   # decided regions, strongest first ([] => unknown)
    confidence: str = "low"                           # high | medium | low
    frameworks: List[str] = field(default_factory=list)
    signals: List[RegionSignal] = field(default_factory=list)
    scores: Dict[str, int] = field(default_factory=dict)

    # --- the five fields the rest of the app persists -------------------------
    @property
    def region(self) -> str:
        return self.regions[0] if self.regions else REGION_UNKNOWN

    @property
    def region_label(self) -> str:
        return ", ".join(REGION_LABELS[r] for r in self.regions) if self.regions else REGION_LABELS[REGION_UNKNOWN]

    @property
    def evidence(self) -> List[str]:
        """Evidence for the decided region(s); for Unknown, every weak hint seen."""
        relevant = [s for s in self.signals if not self.regions or s.region in self.regions]
        seen, out = set(), []
        for s in sorted(relevant, key=lambda s: -s.weight):
            if s.detail not in seen:
                seen.add(s.detail)
                out.append(s.detail)
        return out

    @property
    def applicable_frameworks(self) -> List[str]:
        return list(self.frameworks)

    @property
    def applicability_status(self) -> str:
        return STATUS_DETERMINED if self.frameworks else STATUS_NOT_DETERMINED

    # --- helpers --------------------------------------------------------------
    @property
    def regional_compliance_assessed(self) -> bool:
        return bool(self.frameworks)

    def applies(self, framework: str) -> bool:
        return framework in self.frameworks

    def as_dict(self, assessments: Optional[Dict[str, dict]] = None) -> dict:
        frameworks = []
        for fw in (FW_GDPR, FW_CCPA, FW_DPDP):
            applicable = fw in self.frameworks
            entry = {
                "key": fw,
                "label": FRAMEWORK_LABELS[fw],
                "applicable": applicable,
                "status": "assessed" if applicable else "not_assessed",
                "reason": (
                    f"Applicable — region detected: {self.region_label}."
                    if applicable else
                    ("Not assessed — applicability has not been established." if not self.regions else
                     f"Not assessed — not applicable to the detected region ({self.region_label}).")
                ),
            }
            if applicable and assessments and fw in assessments:
                entry["assessment"] = assessments[fw]
            frameworks.append(entry)
        return {
            "region": self.region,
            "region_label": self.region_label,
            "regions": list(self.regions),
            "confidence": self.confidence,
            "evidence": self.evidence,
            "applicability_status": self.applicability_status,
            "regional_compliance": "assessed" if self.frameworks else "not_assessed",
            "framework_label": (" + ".join(FRAMEWORK_LABELS[f] for f in self.frameworks)
                                if self.frameworks else "Not determined"),
            "frameworks": frameworks,
            "applicable_frameworks": list(self.frameworks),
            "signals": [s.as_dict() for s in self.signals],
            "scores": dict(self.scores),
            "note": (
                "Region could not be established from the site — only the technical consent scan "
                "was run. Framework: not determined. Regional compliance: Not assessed."
                if not self.frameworks else
                "Only frameworks applicable to the detected region were assessed. Applicability is "
                "inferred from public site signals and is not legal advice."
            ),
        }


# Back-compat alias (Phase 1 name).
Applicability = RegionResult


def _normalize_explicit(target_region: Optional[str]) -> Optional[str]:
    if not target_region:
        return None
    key = target_region.strip().lower()
    if key in _REGION_ALIASES:
        return _REGION_ALIASES[key]
    if key in _EU_EEA_TLDS:
        return REGION_EU
    return None


def _url_signals(url: str) -> List[RegionSignal]:
    signals: List[RegionSignal] = []
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    labels = host.split(".")
    tld = labels[-1] if labels else ""

    if tld == "in":
        suffix = ".".join(labels[-2:]) if len(labels) > 2 and labels[-2] in ("co", "gov", "org", "net", "ac") else "in"
        signals.append(RegionSignal(REGION_IN, 60, "tld", f".{suffix} domain"))
    elif tld in _EU_EEA_TLDS:
        signals.append(RegionSignal(REGION_EU, 60, "tld", f"EU country URL (.{tld} domain)"))
    elif tld == "uk":
        signals.append(RegionSignal(REGION_UK, 60, "tld", ".uk domain"))
    elif tld == "us":
        signals.append(RegionSignal(REGION_US_CA, 20, "tld", ".us domain (California not established)"))
    else:
        # Country sections of a global domain: de.example.com / example.com/fr/ / example.com/en-in/
        first_label = labels[0] if len(labels) > 2 else ""
        first_seg = (parsed.path or "/").strip("/").split("/")[0].lower()
        for seg, where in ((first_label, "subdomain"), (first_seg, "path")):
            if not seg:
                continue
            country = seg.split("-")[-1] if "-" in seg else seg
            if country in _EU_URL_SEGMENTS:
                signals.append(RegionSignal(REGION_EU, 35, "url", f"EU country URL ({where} “{seg}”)"))
                break
            if country == "in":
                signals.append(RegionSignal(REGION_IN, 35, "url", f"India URL ({where} “{seg}”)"))
                break
            if country in ("uk", "gb"):
                signals.append(RegionSignal(REGION_UK, 35, "url", f"UK URL ({where} “{seg}”)"))
                break
    return signals


def _lang_signals(page: ParsedPage) -> List[RegionSignal]:
    lang = (page.lang or "").strip().lower().replace("_", "-")
    if not lang:
        return []
    primary, _, region = lang.partition("-")
    region = region.split("-")[0] if region else ""
    if region == "in" or primary in _INDIAN_LANGS:
        return [RegionSignal(REGION_IN, 30, "lang", f'India localisation (lang="{page.lang}")')]
    if region == "gb":
        return [RegionSignal(REGION_UK, 20, "lang", f'UK localisation (lang="{page.lang}")')]
    if region and region != "us" and region in _EU_EEA_TLDS:
        return [RegionSignal(REGION_EU, 30, "lang", f'EU localisation (lang="{page.lang}")')]
    if primary in _EU_LANGS:
        return [RegionSignal(REGION_EU, 20, "lang", f'EU language (lang="{page.lang}")')]
    if region == "us":
        return [RegionSignal(REGION_US_CA, 10, "lang", f'US English (lang="{page.lang}", weak signal)')]
    return []


def _text_signals(text: str, rules, source: str) -> List[RegionSignal]:
    out: List[RegionSignal] = []
    if not text:
        return out
    for pattern, region, weight, desc in rules:
        if pattern.search(text):
            out.append(RegionSignal(region, weight, source, desc))
    return out


def detect_region_signals(url: str, page: Optional[ParsedPage] = None) -> List[RegionSignal]:
    signals = _url_signals(url)
    if page is not None:
        signals += _lang_signals(page)
        signals += _text_signals(page.text_content or "", _TEXT_SIGNALS, "content")
    return signals


def _decide(signals: List[RegionSignal]) -> RegionResult:
    scores: Dict[str, int] = {}
    for s in signals:
        scores[s.region] = scores.get(s.region, 0) + s.weight

    decided = sorted((r for r, sc in scores.items() if sc >= DECISION_THRESHOLD), key=lambda r: -scores[r])
    frameworks: List[str] = []
    for r in decided:
        for fw in REGION_FRAMEWORKS.get(r, []):
            if fw not in frameworks:
                frameworks.append(fw)

    if decided:
        confidence = "high" if scores[decided[0]] >= HIGH_CONFIDENCE else "medium"
    else:
        confidence = "low"
    return RegionResult(regions=decided, confidence=confidence, frameworks=frameworks,
                        signals=signals, scores=scores)


def detect_region(
    url: str,
    page: Optional[ParsedPage] = None,
    target_region: Optional[str] = None,
) -> RegionResult:
    """Step 1 of the consent pipeline: region from URL, language and page text."""
    explicit = _normalize_explicit(target_region)
    if explicit:
        sig = RegionSignal(explicit, 100, "explicit", f"Target region set for this audit: {target_region}")
        return RegionResult(regions=[explicit], confidence="high", frameworks=list(REGION_FRAMEWORKS[explicit]),
                            signals=[sig], scores={explicit: 100})
    return _decide(detect_region_signals(url, page))


def refine_region(result: RegionResult, runtime_result=None) -> RegionResult:
    """
    Step 8: adds what the rendered consent banner says (CMP regional
    configuration) and re-decides. An explicit target region is never
    overridden. Returns `result` unchanged when there's nothing new.
    """
    if any(s.source == "explicit" for s in result.signals):
        return result
    if runtime_result is None or not getattr(runtime_result, "available", False):
        return result
    texts = []
    for panel in (getattr(runtime_result, "banner", None), getattr(runtime_result, "preference_panel", None)):
        if panel and panel.get("banner_detected"):
            texts.append(panel.get("text_excerpt") or "")
    texts += [c.label for c in (getattr(runtime_result, "controls", None) or [])]
    cmp_signals = _text_signals(" ".join(texts), _CMP_SIGNALS, "cmp")
    if not cmp_signals:
        return result
    return _decide(result.signals + cmp_signals)


def determine_applicability(
    url: str,
    page: Optional[ParsedPage] = None,
    target_region: Optional[str] = None,
) -> RegionResult:
    """Phase 1 name for `detect_region` (kept for callers/tests)."""
    return detect_region(url, page, target_region)
