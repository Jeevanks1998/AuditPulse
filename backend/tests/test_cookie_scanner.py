"""
Cookie Scanner tests: one inventory from what the audit observed. Older audits still render.
"""

import asyncio
import time

from reports.cookie_view import build_cookie_inventory, inventory_csv, site_domain

NOW = time.time()


def _ck(name, domain, days=None, secure=True, http_only=False, same_site="Lax"):
    return {"name": name, "domain": domain, "path": "/", "expires": (NOW + days * 86400) if days else None,
            "secure": secure, "http_only": http_only, "same_site": same_site, "size": 30}


def _consent(before, reject, accept, storage=None):
    def cap(cookies, url="https://www.example.ie/"):
        return {"available": True, "cookies": cookies, "page_url": url,
                "local_storage_keys": storage or [], "session_storage_keys": []}
    return {
        "runtime_result": {"available": True, "tested_at": None,
                           "before_consent": cap(before), "after_reject": cap(reject),
                           "after_reject_reload": {"available": False}, "after_accept": cap(accept)},
        "cookies_detected": [],
    }


def test_site_domain():
    assert site_domain("www.axa.ie") == "axa.ie"
    assert site_domain("shop.axa.co.uk") == "axa.co.uk"
    assert site_domain("axa.de") == "axa.de"


def test_inventory_states_party_and_issues():
    ga = _ck("_ga", "example.ie", days=730)
    sess = _ck("JSESSIONID", "www.example.ie", http_only=True)
    consent_cookie = _ck("OptanonConsent", "example.ie", days=365)
    fbp = _ck("_fbp", "example.ie", days=90)
    ide = _ck("IDE", "doubleclick.net", days=390, same_site="None")
    inv = build_cookie_inventory(
        _consent(before=[sess, ga], reject=[sess, consent_cookie], accept=[sess, ga, fbp, ide, consent_cookie],
                 storage=["ajs_user_id"]),
        None, "https://www.example.ie/")

    assert inv["available"]
    by = {c["name"]: c for c in inv["cookies"]}
    assert set(by) == {"_ga", "JSESSIONID", "OptanonConsent", "_fbp", "IDE"}

    ga_row = by["_ga"]
    assert ga_row["category"] == "analytics" and ga_row["party"] == "first"
    assert ga_row["seen"] == {"before_consent": True, "after_reject": False, "after_accept": True, "journey": None}
    assert any("before the visitor gave consent" in i for i in ga_row["issues"])
    assert any("longer than" in i for i in ga_row["issues"])   # 2 years > 13-month guidance
    assert ga_row["status"] == "issue"

    assert by["IDE"]["party"] == "third" and by["IDE"]["category"] == "marketing"
    assert by["IDE"]["seen"]["before_consent"] is False
    assert by["JSESSIONID"]["status"] == "ok" and by["JSESSIONID"]["session"] is True
    assert by["OptanonConsent"]["category"] == "consent_management"

    s = inv["summary"]
    assert s["total"] == 5 and s["third_party"] == 1 and s["before_consent_required"] == 1
    assert s["after_reject_required"] == 0 and s["pages_scanned"] == 1
    assert inv["storage"][0]["key"] == "ajs_user_id"
    assert "set before consent" in inv["headline"]
    # Issues first.
    assert inv["cookies"][0]["status"] == "issue"
    assert any("Only the homepage" in n for n in inv["notes"])


def test_journey_pages_give_page_that_set_cookie():
    journey = {"started_at": None, "pages": [
        {"url": "https://www.example.ie/", "cookies_set": [_ck("JSESSIONID", "www.example.ie", http_only=True)]},
        {"url": "https://www.example.ie/quote", "cookies_set": [_ck("_hjSession_1", "example.ie", days=0.02)]},
        {"url": "https://www.example.ie/contact", "cookies_set": []},
    ]}
    inv = build_cookie_inventory(None, journey, "https://www.example.ie/")
    by = {c["name"]: c for c in inv["cookies"]}
    assert by["_hjSession_1"]["set_by_page"] == "https://www.example.ie/quote"
    assert by["_hjSession_1"]["seen"]["journey"] is True
    assert by["_hjSession_1"]["seen"]["before_consent"] is None      # consent states not tested
    assert inv["summary"]["pages_scanned"] == 3
    assert inv["states_tested"] == ["journey"]


def test_old_audit_without_detail_still_renders():
    old = _consent(before=[{"name": "_ga", "domain": ".example.ie", "category": "analytics"}], reject=[], accept=[])
    inv = build_cookie_inventory(old, {"pages": [{"url": "https://www.example.ie/"}]}, "https://www.example.ie/")
    c = inv["cookies"][0]
    assert c["detail_missing"] and c["lifetime_label"] == "Not recorded"
    assert any("earlier version" in n for n in inv["notes"])
    assert any("Journey Map ran before" in n for n in inv["notes"])


def test_server_set_cookie_counts_as_before_consent():
    consent = {"runtime_result": None, "cookies_detected": [
        {"name": "_gcl_au", "domain": "example.ie", "category": "marketing", "expires": 90}]}
    inv = build_cookie_inventory(consent, None, "https://www.example.ie/")
    c = inv["cookies"][0]
    assert c["seen"]["before_consent"] is True and c["requires_consent"]


def test_nothing_ran():
    inv = build_cookie_inventory(None, None, "https://www.example.ie/")
    assert not inv["available"] and inv["cookies"] == []


def test_csv_export():
    inv = build_cookie_inventory(_consent([_ck("_ga", "example.ie", days=400)], [], []), None, "https://www.example.ie/")
    text = inventory_csv(inv)
    lines = text.strip().splitlines()
    assert lines[0].startswith("Name,Domain,Path,Party,Category")
    assert lines[1].startswith("_ga,example.ie,/,First,Analytics")
    assert "Not tested" in lines[1]          # journey column


def test_pdf_has_cookie_section():
    from pdf.pdf_generator import generate_pdf_report
    from reports.generator import build_report_payload

    consent = _consent([_ck("_ga", "example.ie", days=730)], [], [_ck("_fbp", "example.ie", days=90)])
    payload = asyncio.run(build_report_payload(
        audit_id=1, url="https://www.example.ie/", overall=50, generated_at="2026-10-22T10:00:00+00:00",
        breakdown={}, findings=[], consent=None, journey=None))
    payload.cookie_inventory = build_cookie_inventory(consent, None, "https://www.example.ie/")
    pdf = generate_pdf_report(payload)
    assert pdf[:4] == b"%PDF" and len(pdf) > 2000


def test_httponly_rule_only_for_login_style_cookies():
    inv = build_cookie_inventory(_consent([], [], [_ck("_hjSessionUser_1", "example.ie", days=30),
                                                   _ck("app_session", "www.example.ie")]), None,
                                 "https://www.example.ie/")
    by = {c["name"]: c for c in inv["cookies"]}
    assert not any("HttpOnly" in i for i in by["_hjSessionUser_1"]["issues"])
    assert any("HttpOnly" in i for i in by["app_session"]["issues"])


def test_cmp_cookies_recognised():
    from cookies.categories import classify_cookie
    assert classify_cookie("_evidon_consent_cookie").category == "consent_management"
    assert classify_cookie("TC_PRIVACY").category == "consent_management"


def test_site_pages_from_consent_sweep_count_as_other_pages():
    consent = _consent([_ck("JSESSIONID", "www.example.ie", http_only=True)], [], [_ck("_ga", "example.ie", days=300)])
    consent["runtime_result"]["site_pages"] = [
        {"url": "https://www.example.ie/car", "cookies_set": [_ck("_fbp", "example.ie", days=90)]},
        {"url": "https://www.example.ie/home", "cookies_set": []},
        {"url": "https://www.example.ie/broken", "error": "timeout", "cookies_set": []},
    ]
    inv = build_cookie_inventory(consent, None, "https://www.example.ie/")
    by = {c["name"]: c for c in inv["cookies"]}
    assert by["_fbp"]["seen"]["journey"] is True and by["_fbp"]["set_by_page"] == "https://www.example.ie/car"
    assert by["_ga"]["seen"]["journey"] is False
    assert inv["summary"]["pages_scanned"] == 3          # homepage + 2 visited (the failed one excluded)
    assert not any("Only the homepage" in n for n in inv["notes"])


def test_server_only_cookie_does_not_trigger_old_version_note():
    consent = _consent([_ck("TCPID", "example.ie", days=300)], [], [])
    consent["cookies_detected"] = [{"name": "AKTIONSCODE", "domain": "www.example.ie", "category": "unknown",
                                    "expires": "session"}]
    inv = build_cookie_inventory(consent, None, "https://www.example.ie/")
    assert not any("earlier version" in n for n in inv["notes"])


def test_cookie_scan_urls_same_site_only():
    from bs4 import BeautifulSoup
    from services.audit_service import _cookie_scan_urls

    html = ('<a href="/car">Car</a><a href="/car#top">dup</a><a href="https://shop.example.ie/x">sub</a>'
            '<a href="https://other.com/">ext</a><a href="/doc.pdf">pdf</a><a href="mailto:a@b.c">m</a>'
            '<a href="https://www.example.ie/">home</a><a href="/home">home2</a>')

    class P:
        anchor_tags = BeautifulSoup(html, "html.parser").find_all("a")

    urls = _cookie_scan_urls("https://www.example.ie/", P(), limit=5)
    assert urls == ["https://www.example.ie/car", "https://shop.example.ie/x", "https://www.example.ie/home"]
