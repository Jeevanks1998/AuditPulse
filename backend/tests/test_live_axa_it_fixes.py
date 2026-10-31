"""
Fixes from the live axa.it audit after the pilot-feedback release:
- a slow "load" event no longer fails the consent browser check (false "No banner");
- when no browser visit opened the site, consent is "not tested" and not scored;
- tel:// phone links are valid;
- dual GA4 tagging is not a "duplicate" loader / Page View.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from consent import _browser_reached_site  # noqa: E402
from consent.navigation import open_page  # noqa: E402
from journey.journey_interactions import contact_link_check  # noqa: E402
from analytics.runtime import CapturedRequest, _has_duplicate_page_view  # noqa: E402
from services.audit_service import _compute_overall_score  # noqa: E402


class FakePage:
    def __init__(self, commit: bool, fail_retry: bool = False):
        self.url = "about:blank"
        self.commit, self.fail_retry, self.calls = commit, fail_retry, []

    async def goto(self, url, wait_until, timeout):
        self.calls.append(wait_until)
        if wait_until == "load":
            if self.commit:
                self.url = url
            raise TimeoutError("Page.goto: Timeout 20000ms exceeded")
        if self.fail_retry:
            raise TimeoutError("still nothing")
        self.url = url

    async def wait_for_load_state(self, state, timeout):
        return None


def test_slow_load_uses_the_rendered_page():
    page = FakePage(commit=True)
    asyncio.run(open_page(page, "https://www.axa.it", 20_000))
    assert page.calls == ["load"] and page.url == "https://www.axa.it"


def test_page_that_did_not_open_is_retried_once():
    page = FakePage(commit=False)
    asyncio.run(open_page(page, "https://www.axa.it", 20_000))
    assert page.calls == ["load", "domcontentloaded"]
    bad = FakePage(commit=False, fail_retry=True)
    try:
        asyncio.run(open_page(bad, "https://www.axa.it", 20_000))
        raised = False
    except TimeoutError:
        raised = True
    assert raised


def _cap(ok):
    return SimpleNamespace(available=ok)


def _rt(banner=False, ok=False):
    return SimpleNamespace(banner_detected=banner, before_consent=_cap(ok), before_accept=_cap(False),
                           after_reject=_cap(False), after_accept=_cap(False))


def test_consent_not_tested_only_when_no_browser_visit_opened_the_site():
    failed_net = SimpleNamespace(available=False)
    assert _browser_reached_site(True, True, False, failed_net, _rt()) is False
    assert _browser_reached_site(True, True, False, failed_net, _rt(ok=True)) is True     # page opened, no banner
    assert _browser_reached_site(True, True, False, SimpleNamespace(available=True), _rt()) is True
    assert _browser_reached_site(True, True, True, failed_net, _rt()) is True             # static banner seen
    assert _browser_reached_site(False, False, False, None, None) is True                 # live checks off


def test_untested_consent_is_left_out_of_the_overall_score():
    assert _compute_overall_score({"consent": None, "analytics": 80}) == 80
    assert _compute_overall_score({"consent": None}) is None


def test_consent_view_shows_not_tested():
    from reports.consent_view import build_consent_view
    view = build_consent_view({"consent_score": 91, "has_cookie_banner": False,
                               "applicability": {"region_label": "Italy"},
                               "technical_scan": {"scan": {"browser_tested": False}}})
    assert view["status"]["score"] is None
    banner = next(t for t in view["tiles"] if t["key"] == "banner")
    assert banner["value"] == "Not tested" and banner["state"] == "not_tested"


def test_phone_links_written_as_tel_slash_slash_are_valid():
    assert contact_link_check("tel://800085559")[0]
    assert contact_link_check("tel:+39 02 1234 5678")[0]
    assert contact_link_check("mailto:info@axa.it")[0]
    assert not contact_link_check("tel:call-us")[0]


def _pv(tid):
    return CapturedRequest(url="https://region1.google-analytics.com/g/collect", phase="load", vendor_key="ga4",
                           event_name="page_view", is_page_view=True, identifier=tid)


def test_one_page_view_per_ga4_property_is_not_a_duplicate():
    assert not _has_duplicate_page_view("ga4", [_pv("G-AAA"), _pv("G-BBB")])
    assert _has_duplicate_page_view("ga4", [_pv("G-AAA"), _pv("G-AAA")])
    assert not _has_duplicate_page_view("tagcommander", [_pv("a"), _pv("a")])


def test_one_gtag_loader_per_property_is_not_loaded_twice():
    from bs4 import BeautifulSoup
    from analytics.ga4 import detect_ga4
    html = ('<script async src="https://www.googletagmanager.com/gtag/js?id=G-AAA"></script>'
            '<script async src="https://www.googletagmanager.com/gtag/js?id=G-BBB"></script>'
            "<script>gtag('config','G-AAA');gtag('config','G-BBB');</script>")
    page = SimpleNamespace(soup=BeautifulSoup(html, "html.parser"), url="https://x.it", html=html)
    det = detect_ga4(page)
    assert det.repeated_loader_count == 0
    html2 = html + '<script async src="https://www.googletagmanager.com/gtag/js?id=G-AAA"></script>'
    page2 = SimpleNamespace(soup=BeautifulSoup(html2, "html.parser"), url="https://x.it", html=html2)
    assert detect_ga4(page2).repeated_loader_count == 1
