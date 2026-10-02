"""
End-to-end consent scans against local fixture sites in a real Chromium:
static fetch -> consent.analyze_site(enable_live_checks, enable_runtime_checks)
-> ConsentSummary, exactly as services.audit_service runs it.
"""

import asyncio
from urllib.parse import urlparse

import pytest

from tests.consent.conftest import chromium_available, fetch, site_url

pytestmark = pytest.mark.skipif(not chromium_available(), reason="Chromium not available")

_CACHE = {}


def scan(host, site_server, target_region=None):
    key = (host, target_region)
    if key in _CACHE:
        return _CACHE[key]
    import consent
    from cookies.detector import parse_set_cookie_headers
    from crawler.parser import parse_html

    url = site_url(host)
    html, set_cookies = fetch(host)
    page = parse_html(url, html)
    cookies = parse_set_cookie_headers(set_cookies, source_url=url)
    result = asyncio.run(consent.analyze_site(
        url, page, cookies=cookies, first_party_hostname=urlparse(url).hostname,
        enable_live_checks=True, enable_runtime_checks=True, target_region=target_region,
    ))
    _CACHE[key] = result
    return result


def _controls(result, layer=1):
    return {c["label"]: c["action"] for c in result.summary.technical_scan["controls"] if c["layer"] == layer}


# --- EU site, client-rendered OneTrust-style banner, GTM pre-consent --------
def test_eu_client_rendered_cmp(site_server):
    r = scan("www.example-shop.de", site_server)
    rt = r.runtime_result
    s = r.summary

    # Banner found in the rendered DOM; only its controls are inventoried.
    assert rt.banner_detected and rt.banner["detected_via"] == "cmp_selector"
    assert _controls(r) == {
        "Accept All Cookies": "accept_all",
        "Reject All": "reject_all",
        "Cookie Settings": "manage_preferences",
    }
    assert all(c["evidence"] == "Rendered consent banner"
               for c in s.technical_scan["controls"] if c["layer"] == 1)
    # The unrelated checkout "Continue" and nav "Settings" were never candidates.
    assert "Continue" not in _controls(r) and "Settings" not in _controls(r)

    # Clicked exactly the inventoried controls.
    assert rt.accept_clicked_label == "Accept All Cookies"
    assert rt.reject_clicked_label == "Reject All" and rt.reject_layer == 1
    assert rt.manage_clicked_label == "Cookie Settings" and rt.personalize_exposes_controls is True
    assert _controls(r, layer=2) == {"Confirm My Choices": "save_preferences", "Reject All": "reject_all"}

    # GTM before consent = observation; GA collect only after Accept.
    assert rt.before_consent.tracker_requests == []
    assert any(q.vendor == "Google Tag Manager" for q in rt.before_consent.vendor_requests)
    assert rt.reject_blocks_tracking is True
    assert rt.accept_allows_tracking is True
    titles = [f["title"] for f in r.findings]
    assert "Tracking activity before consent" not in titles
    assert "Observation: tag manager loaded before consent" in titles
    # XSRF-TOKEN is JS-readable by design — no HttpOnly finding for it.
    assert not any("XSRF-TOKEN" in t for t in titles)

    # OptanonConsent / XSRF-TOKEN / session are not failures.
    assert s.gdpr_checks["cookies_blocked_pre_consent"] is True
    assert s.gdpr_checks["trackers_blocked_pre_consent"] is True
    ck = s.technical_scan["cookies_before_consent"]
    assert any(x.startswith("OptanonConsent") for x in ck["consent_management"])

    # Applicability: .de -> GDPR only; CCPA not assessed.
    assert s.applicability["applicable_frameworks"] == ["gdpr"]
    assert s.ccpa_checks == {}
    assert s.gdpr_checks["accept_control"] and s.gdpr_checks["reject_control"] and s.gdpr_checks["reject_parity"]
    assert s.gdpr_compliant is True


# --- Unknown region, tracking before consent, "necessary only" keeps tracking -----
def test_global_site_tracking_and_unknown_region(site_server):
    r = scan("www.globalco.com", site_server)
    rt, s = r.runtime_result, r.summary

    assert _controls(r) == {
        "Accept only strictly necessary cookies": "reject_non_essential",
        "Accept all": "accept_all",
        "Personalize": "manage_preferences",
    }
    assert rt.reject_clicked_label == "Accept only strictly necessary cookies"
    assert rt.accept_clicked_label == "Accept all"  # not the page's generic "Continue"
    # "Personalize" does nothing on this site: no panel, so no layer-2 controls.
    assert rt.manage_clicked and rt.personalize_exposes_controls is False
    assert _controls(r, layer=2) == {}

    # GA collect before consent is real tracking evidence.
    assert [q.vendor for q in rt.before_consent.tracker_requests] == ["Google Analytics"]
    assert "Tracking activity before consent" in [f["title"] for f in r.findings]
    assert rt.reject_blocks_tracking is False  # Meta pixel + _fbp after "necessary only"
    assert s.technical_scan["checks"]["cookies_blocked_pre_consent"] is False
    ev = s.technical_scan["evidence"]["cookies_blocked_pre_consent"]
    assert any(i.startswith("_ga") for i in ev["items"])
    assert not any(i.startswith("foo_pref") for i in ev["items"])  # unknown is not a failure

    # No region -> no GDPR/CCPA verdicts at all.
    assert s.applicability["regional_compliance"] == "not_assessed"
    assert s.gdpr_checks == {} and s.ccpa_checks == {}
    assert s.gdpr_compliant is False and s.ccpa_compliant is False


def test_global_site_with_explicit_region(site_server):
    r = scan("www.globalco.com", site_server, target_region="EU")
    s = r.summary
    assert s.applicability["applicable_frameworks"] == ["gdpr"]
    assert s.gdpr_checks["trackers_blocked_pre_consent"] is False
    assert s.gdpr_checks["reject_blocks_tracking"] is False
    assert s.gdpr_compliant is False


# --- India, CMP inside an iframe; an unrelated "Accept" dialog on the page --------
def test_iframe_cmp_india(site_server):
    r = scan("news.example.in", site_server)
    rt, s = r.runtime_result, r.summary
    assert rt.banner_detected
    assert "privacy-mgmt.com" in rt.banner["frame"]
    assert _controls(r) == {
        "Accept": "accept",
        "Continue without accepting": "reject_non_essential",
        "×": "dismiss",
    }
    assert all("iframe" in c["evidence"] for c in s.technical_scan["controls"])
    # Terms-of-service dialog's "Accept"/"OK" were not treated as consent controls.
    assert rt.accept_clicked and rt.reject_clicked
    assert rt.reject_clicked_label == "Continue without accepting"
    assert s.applicability["applicable_frameworks"] == ["dpdp"]
    dpdp = next(f for f in s.applicability["frameworks"] if f["key"] == "dpdp")["assessment"]
    assert dpdp["checks"]["affirmative_consent_action"] is True
    assert dpdp["checks"]["refusal_available"] is True
    assert s.gdpr_checks == {} and s.ccpa_checks == {}


# --- UK banner with only OK / Got it / Close ---------------------------------------
def test_ok_and_close_are_not_accept_or_reject(site_server):
    r = scan("shop.example.co.uk", site_server)
    rt, s = r.runtime_result, r.summary
    acts = _controls(r)
    assert acts == {"OK": "acknowledge", "Got it": "acknowledge", "Close": "dismiss"}
    assert not rt.accept_button_found and not rt.reject_button_found
    assert not rt.accept_clicked and not rt.reject_clicked
    assert s.applicability["applicable_frameworks"] == ["gdpr"]
    assert s.gdpr_checks["accept_control"] is False
    assert s.gdpr_checks["reject_control"] is False


# --- No banner at all: unrelated "Accept order"/"Continue" never become consent ---
def test_no_banner(site_server):
    r = scan("plain.example.com", site_server)
    rt, s = r.runtime_result, r.summary
    assert not rt.banner_detected
    assert s.technical_scan["controls"] == []
    assert not rt.accept_clicked and not rt.reject_clicked
    assert s.has_cookie_banner is False


# --- Only "Continue without accepting": recorded, nothing assumed -----------------
def test_continue_without_accepting_only(site_server):
    r = scan("boutique.example.fr", site_server)
    rt, s = r.runtime_result, r.summary
    assert _controls(r) == {"Continue without accepting": "reject_non_essential"}
    assert s.consent_controls == [{"label": "Continue without accepting", "action": "reject_non_essential",
                                   "evidence": "Rendered consent banner", "layer": 1}]
    assert rt.reject_clicked_label == "Continue without accepting"
    assert not rt.accept_button_found and not rt.accept_clicked      # no Accept invented
    assert rt.after_accept.available is False
    assert s.detected_region == "EU" and s.applicable_frameworks == ["gdpr"]
    assert s.gdpr_checks["accept_control"] is False


# --- Phase 2 columns ---------------------------------------------------------------
def test_region_columns(site_server):
    s = scan("news.example.in", site_server).summary
    assert s.detected_region == "IN" and s.region_confidence == "high"
    assert s.applicability_status == "determined" and s.applicable_frameworks == ["dpdp"]
    assert any("domain" in e for e in s.region_evidence)
    u = scan("www.globalco.com", site_server).summary
    assert (u.detected_region, u.region_confidence, u.applicability_status) == ("UNKNOWN", "low", "not_determined")


# --- Phase 3: every scan is fresh ----------------------------------------------------
def test_every_scan_is_fresh(site_server):
    import os
    a = scan("www.example-shop.de", site_server)
    _CACHE.pop(("www.example-shop.de", None))
    b = scan("www.example-shop.de", site_server)
    assert a.scan_id != b.scan_id
    for res in (a, b):
        rt = res.runtime_result
        assert rt.fresh_contexts == 2
        # Earlier scans accepted (and set _ga), yet each scan starts clean:
        assert not any(c.name == "_ga" for c in rt.before_consent.cookies)
        assert not any(c.name == "_ga" for c in rt.before_accept.cookies)
        assert any(c.name == "_ga" for c in rt.after_accept.cookies)
        assert rt.before_consent.local_storage_keys == []
        scan_meta = res.summary.technical_scan["scan"]
        assert scan_meta["scan_id"] == res.scan_id and scan_meta["fresh"] is True
        assert [p["step"] for p in res.pipeline] == list(range(1, 12))
    shots_a = [a.summary.banner_screenshot_path, a.summary.preferences_screenshot_path,
               a.summary.reject_screenshot_path, a.summary.accept_screenshot_path]
    shots_b = [b.summary.banner_screenshot_path, b.summary.preferences_screenshot_path,
               b.summary.reject_screenshot_path, b.summary.accept_screenshot_path]
    assert all(shots_a) and all(shots_b) and not set(shots_a) & set(shots_b)
    assert all(os.path.exists(p) for p in shots_a + shots_b)


def test_leg_one_order_and_banner_clip(site_server):
    from PIL import Image
    r = scan("www.example-shop.de", site_server)
    log = r.runtime_result.leg_log
    manage_i = next(i for i, l in enumerate(log) if "Cookie Settings" in l)
    reject_i = next(i for i, l in enumerate(log) if "clicked 'Reject All'" in l)
    assert manage_i < reject_i               # Manage/Personalize before Reject in leg 1
    assert r.runtime_result.reject_layer == 1  # parity judged on the first layer
    # The initial screenshot is clipped to the detected banner, not the full viewport.
    w, h = Image.open(r.summary.banner_screenshot_path).size
    assert h < 400 and w > 600
