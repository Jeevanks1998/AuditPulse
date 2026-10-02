"""Unit tests for Phase 1 classifiers — no browser needed."""

import pytest

from consent.ccpa import detect_ccpa_signals
from consent.preferences import PreferencesDetection, check_preferences, verify_preferences_runtime
from consent.region import FW_CCPA, FW_DPDP, FW_GDPR, detect_region, determine_applicability, refine_region
from consent.buttons import (
    ACCEPT, ACCEPT_ALL, ACKNOWLEDGE, DISMISS, MANAGE_PREFERENCES, REJECT, REJECT_ALL,
    REJECT_NON_ESSENTIAL, UNCLASSIFIED, classify_label, detect_buttons,
)
from consent.cookies import bucket_cookies, check_pre_consent_cookies
from consent.network import (
    ADVERTISING, ANALYTICS, CMP, CONTENT_CDN, FONT, TAG_MANAGER, PreConsentNetworkResult,
    check_pre_consent_network, classify_request,
)
from cookies.categories import (
    ANALYTICS as C_ANALYTICS, CONSENT_MANAGEMENT, ESSENTIAL, MARKETING, UNKNOWN,
    categorize_cookie, classify_cookie, display_name,
)
from cookies.detector import parse_set_cookie_headers
from crawler.parser import parse_html


# ---------------------------------------------------------------- buttons ---
@pytest.mark.parametrize("label,action", [
    ("Accept all", ACCEPT_ALL), ("Accept All Cookies", ACCEPT_ALL), ("Accept", ACCEPT),
    ("Reject all", REJECT_ALL), ("Reject", REJECT),
    ("Necessary only", REJECT_NON_ESSENTIAL),
    ("Accept only strictly necessary cookies", REJECT_NON_ESSENTIAL),
    ("Continue without accepting", REJECT_NON_ESSENTIAL),
    ("Personalize", MANAGE_PREFERENCES), ("Manage preferences", MANAGE_PREFERENCES),
    ("Continue", ACKNOWLEDGE),          # generic continue is NOT accept
    ("OK", ACKNOWLEDGE),                # OK is NOT accept
    ("Got it", ACKNOWLEDGE),
    ("Close", DISMISS), ("Dismiss", DISMISS), ("×", DISMISS),  # close/dismiss are NOT reject
    ("Sign up", UNCLASSIFIED),
])
def test_label_classification(label, action):
    assert classify_label(label) == action


def test_static_buttons_scoped_to_banner():
    html = """<html><body>
      <form><button>Continue</button><button>Accept order</button></form>
      <nav><a href="/settings">Settings</a></nav>
      <div id="cookie-banner"><p>We use cookies.</p>
        <button>Accept only strictly necessary cookies</button><button>Accept all</button>
        <button>Personalize</button></div></body></html>"""
    det = detect_buttons(parse_html("https://x.example/", html))
    assert det.container_found
    labels = {c.label: c.action for c in det.controls}
    assert labels == {
        "Accept only strictly necessary cookies": REJECT_NON_ESSENTIAL,
        "Accept all": ACCEPT_ALL,
        "Personalize": MANAGE_PREFERENCES,
    }
    assert "Continue" not in labels and "Settings" not in labels
    assert det.accept_found and det.reject_found and det.manage_found


def test_static_no_banner_means_no_controls():
    html = "<html><body><button>Continue</button><button>Accept order</button><a>Settings</a></body></html>"
    det = detect_buttons(parse_html("https://x.example/", html))
    assert not det.container_found
    assert not (det.accept_found or det.reject_found or det.manage_found)


# ---------------------------------------------------------------- network ---
def test_gtm_is_observation_not_tracking():
    r = classify_request("https://www.googletagmanager.com/gtm.js?id=GTM-X", "script", "axa.com")
    assert r.category == TAG_MANAGER and not r.is_tracking and r.is_observation
    r = classify_request("https://www.googletagmanager.com/gtag/js?id=G-X", "script", "axa.com")
    assert r.category == TAG_MANAGER and not r.is_tracking


def test_ga_collect_is_tracking():
    r = classify_request("https://region1.google-analytics.com/g/collect?v=2&tid=G-X", "ping", "axa.com")
    assert r.category == ANALYTICS and r.is_tracking
    # server-side / first-party GA4 tagging still counts
    r = classify_request("https://sst.axa.com/g/collect?v=2&tid=G-X&en=page_view", "fetch", "axa.com")
    assert r.category == ANALYTICS and r.is_tracking


@pytest.mark.parametrize("url,rtype,cat", [
    ("https://stats.g.doubleclick.net/g/collect?v=2", "image", ADVERTISING),
    ("https://fonts.gstatic.com/s/roboto.woff2", "font", FONT),
    ("https://fonts.googleapis.com/css2?family=Roboto", "stylesheet", FONT),
    ("https://cdn.cookielaw.org/scripttemplates/otSDKStub.js", "script", CMP),
    ("https://cdnjs.cloudflare.com/ajax/libs/jquery.js", "script", CONTENT_CDN),
])
def test_request_categories(url, rtype, cat):
    assert classify_request(url, rtype, "axa.com").category == cat


def test_loader_without_collection_is_not_tracking():
    r = classify_request("https://connect.facebook.net/en_US/fbevents.js", "script", "x.com")
    assert r.category == ADVERTISING and not r.is_tracking
    r = classify_request("https://www.facebook.com/tr?id=1&ev=PageView", "image", "x.com")
    assert r.is_tracking


def test_network_findings_gtm_only():
    res = PreConsentNetworkResult(available=True, requests=[
        classify_request("https://www.googletagmanager.com/gtm.js?id=GTM-X", "script", "axa.com"),
        classify_request("https://cdn.cookielaw.org/consent/abc.json", "fetch", "axa.com"),
    ])
    titles = [f["title"] for f in check_pre_consent_network(res)]
    assert "Tracking activity before consent" not in titles
    assert any("Observation: tag manager" in t for t in titles)
    assert res.tracker_requests == []


def test_network_findings_ga_collect():
    res = PreConsentNetworkResult(available=True, requests=[
        classify_request("https://www.googletagmanager.com/gtm.js?id=GTM-X", "script", "axa.com"),
        classify_request("https://www.google-analytics.com/g/collect?v=2&tid=G-X", "ping", "axa.com"),
    ])
    findings = check_pre_consent_network(res)
    crit = [f for f in findings if f["severity"] == "critical"]
    assert len(crit) == 1 and crit[0]["title"] == "Tracking activity before consent"
    assert "Google Analytics" in crit[0]["description"]


# ---------------------------------------------------------------- cookies ---
@pytest.mark.parametrize("name,cat", [
    ("OptanonConsent", CONSENT_MANAGEMENT), ("OptanonAlertBoxClosed", CONSENT_MANAGEMENT),
    ("CookieConsent", CONSENT_MANAGEMENT), ("euconsent-v2", CONSENT_MANAGEMENT),
    ("XSRF-TOKEN", ESSENTIAL), ("session", ESSENTIAL), ("csrftoken", ESSENTIAL),
    ("_csrf", ESSENTIAL), ("my_app_session", ESSENTIAL), ("AWSALB", ESSENTIAL),
    ("_ga", C_ANALYTICS), ("_ga_ABC123", C_ANALYTICS), ("_hjSession_123", C_ANALYTICS),
    ("_fbp", MARKETING), ("_gcl_au", MARKETING),
    ("foo_pref", UNKNOWN), ("x7f", UNKNOWN),
])
def test_cookie_categories(name, cat):
    assert categorize_cookie(name) == cat


def test_optanon_display_and_purpose():
    cls = classify_cookie("OptanonConsent")
    assert display_name(cls.category) == "Consent management"
    assert cls.purpose == "consent_storage" and not cls.requires_consent


def test_xsrf_session_not_a_consent_failure():
    cookies = parse_set_cookie_headers(
        ["XSRF-TOKEN=abc; Path=/", "session=1; Path=/", "OptanonConsent=x; Path=/", "mystery=1; Path=/"],
        source_url="https://x.example/",
    )
    findings = check_pre_consent_cookies(cookies)
    assert not any(f["severity"] == "critical" for f in findings)
    assert any("Unclassified" in f["title"] and f["severity"] == "info" for f in findings)
    b = bucket_cookies(cookies)
    assert [c.name for c in b.essential] == ["XSRF-TOKEN", "session"]
    assert [c.name for c in b.consent_management] == ["OptanonConsent"]
    assert [c.name for c in b.unknown] == ["mystery"]
    assert b.consent_required == []


def test_analytics_cookie_in_response_is_flagged():
    cookies = parse_set_cookie_headers(["_ga=GA1.1.1.1; Path=/"], source_url="https://x.example/")
    assert any(f["severity"] == "critical" for f in check_pre_consent_cookies(cookies))


# ----------------------------------------------------------- applicability ---
def _page(url, html):
    return parse_html(url, html)


def test_unknown_region_assesses_nothing():
    app = determine_applicability("https://www.axa.com/", _page(
        "https://www.axa.com/", '<html lang="en"><body><p>Insurance and asset management.</p></body></html>'))
    assert app.frameworks == []
    d = app.as_dict()
    assert d["regional_compliance"] == "not_assessed" and d["region"] == "UNKNOWN"
    assert all(f["status"] == "not_assessed" for f in d["frameworks"])


def test_en_us_alone_is_not_california():
    app = determine_applicability("https://x.com/", _page("https://x.com/", '<html lang="en-US"><body>Hi</body></html>'))
    assert app.frameworks == []


def test_india_dpdp():
    app = determine_applicability("https://shop.example.in/", None)
    assert app.frameworks == [FW_DPDP]


def test_eu_gdpr_and_ca_candidate():
    assert determine_applicability("https://shop.example.de/", None).frameworks == [FW_GDPR]
    page = _page("https://x.com/", '<html lang="en-US"><body><a>Do Not Sell or Share My Personal Information</a>'
                                   '<p>California Privacy Rights</p></body></html>')
    assert determine_applicability("https://x.com/", page).frameworks == [FW_CCPA]


def test_explicit_region_override():
    assert determine_applicability("https://www.axa.com/", None, target_region="EU").frameworks == [FW_GDPR]


# ------------------------------------------------------------ region engine ---
def test_region_india_high_confidence_with_evidence():
    page = _page("https://shop.example.in/", '<html lang="en-IN"><body><p>Prices ₹ 499. Grievance Officer: '
                                             'privacy@shop.in. DPDP Act 2023.</p></body></html>')
    r = detect_region("https://shop.example.in/", page)
    assert r.region == "IN" and r.confidence == "high"
    assert r.applicable_frameworks == [FW_DPDP] and r.applicability_status == "determined"
    assert ".in domain" in r.evidence
    assert any("India-specific privacy text" in e for e in r.evidence)
    assert any("India localisation" in e for e in r.evidence)


def test_region_eu_medium_from_country_url_and_gdpr_text():
    page = _page("https://www.example.com/fr/", '<html lang="en"><body><p>We process data under the GDPR '
                                                '(General Data Protection Regulation).</p></body></html>')
    r = detect_region("https://www.example.com/fr/", page)
    assert r.region == "EU" and r.confidence == "medium" and r.applicable_frameworks == [FW_GDPR]
    assert any("EU country URL" in e for e in r.evidence) and "GDPR reference" in r.evidence
    assert r.as_dict()["framework_label"] == "GDPR + ePrivacy"


def test_region_unknown_low_not_determined():
    r = detect_region("https://www.axa.com/", _page("https://www.axa.com/", '<html lang="en"><body>Hi</body></html>'))
    d = r.as_dict()
    assert (r.region, r.confidence, r.applicability_status) == ("UNKNOWN", "low", "not_determined")
    assert d["framework_label"] == "Not determined" and d["regional_compliance"] == "not_assessed"


def test_refine_region_with_cmp_configuration():
    class RT:
        available = True
        banner = {"banner_detected": True, "text_excerpt": "We use cookies. Do Not Sell or Share My Personal "
                                                          "Information. Your Privacy Choices."}
        preference_panel = None
        controls = []
    base = detect_region("https://x.com/", _page("https://x.com/", '<html lang="en-US"><body>'
                                                 '<p>California Privacy Rights</p></body></html>'))
    assert base.frameworks == []          # 10 + 30 = 40 < threshold
    refined = refine_region(base, RT())
    assert refined.frameworks == [FW_CCPA]
    assert any(e.startswith("CMP regional configuration") for e in refined.evidence)
    # explicit region is never overridden
    explicit = detect_region("https://x.com/", None, target_region="IN")
    assert refine_region(explicit, RT()).frameworks == [FW_DPDP]


# ------------------------------------------------------------- ccpa signals ---
def test_ccpa_signals_only_detect():
    page = _page("https://x.com/", '<html><body><a href="/dns">Do Not Sell or Share My Personal Information</a>'
                                   '<script>if (navigator.globalPrivacyControl) {}</script></body></html>')
    sig = detect_ccpa_signals(page)
    assert sig.do_not_sell_link and sig.gpc_handling and sig.privacy_choices.found
    assert not hasattr(sig, "applies")  # applicability belongs to consent.region


# -------------------------------------------------------------- preferences ---
def test_preferences_runtime_verification():
    class RT:
        available = True
        manage_clicked = True
        manage_clicked_label = "Personalize"
        personalize_exposes_controls = False
        preference_panel = {"banner_detected": False}
    det = verify_preferences_runtime(PreferencesDetection(link_found=True), RT())
    assert det.panel_verified is False
    page = _page("https://x.com/", "<html><body></body></html>")
    titles = [f["title"] for f in check_preferences(page, True, detection=det)]
    assert titles == ["Manage preferences did not open a preference panel"]


# ------------------------------------------------- Phase 4: report view ---
def test_consent_view_unknown_region_not_assessed():
    from reports.consent_view import build_consent_view
    view = build_consent_view({
        "has_cookie_banner": True, "gdpr_checks": {}, "ccpa_checks": {},
        "applicability": {"region": "UNKNOWN", "region_label": "Unknown", "confidence": "low",
                          "applicable_frameworks": [], "frameworks": [], "framework_label": "Not determined"},
        "technical_scan": {"network": {"before_consent": {
            "TAG_MANAGER": {"label": "Tag manager", "count": 1, "tracking_count": 0, "vendors": ["Google Tag Manager"]},
            "ANALYTICS": {"label": "Analytics", "count": 2, "tracking_count": 1, "vendors": ["Google Analytics"]},
            "CMP": {"label": "CMP", "count": 3, "tracking_count": 0, "vendors": ["OneTrust"]}}},
            "checks": {"trackers_blocked_pre_consent": False}},
        "runtime_result": {"reject_blocks_tracking": None},
    })
    assert view["status"]["regional_compliance"] == "not_assessed"
    assert all(f["status"] == "not_assessed" for f in view["frameworks"])
    kinds = {r["category"]: r["kind"] for r in view["network"]["before_consent"]}
    assert kinds == {"TAG_MANAGER": "observation", "ANALYTICS": "tracking", "CMP": "infrastructure"}
    tiles = {t["key"]: t for t in view["tiles"]}
    assert tiles["tracking"]["state"] == "fail" and tiles["reject"]["state"] == "not_tested"
    assert [s["captured"] for s in view["screenshots"]] == [False] * 4


def test_consent_view_legacy_row():
    from reports.consent_view import build_consent_view
    view = build_consent_view({"has_cookie_banner": False, "gdpr_checks": {"consent_banner": False},
                               "ccpa_checks": {"privacy_policy_available": True}})
    assert view["legacy"] is True
    assert [f["key"] for f in view["frameworks"] if f["applicable"]] == ["gdpr", "ccpa"]
    assert next(f for f in view["frameworks"] if f["key"] == "gdpr")["status"] == "fail"
