"""
Journey Map robustness on real sites: elements are found again by signature
(element order changes between loads), a time limit keeps partial results,
and an audit with no score is "not scored", not 0.
"""

import asyncio
import time

import pytest

from journey.journey_interactions import Interaction, relocate_element
from tests.journey.conftest import site_url


def _it(**kw):
    base = dict(index=1, element_id="p1e57", page_url="https://www.example.com/", label="Get a quote", tag="a",
                classification="cta", classification_label="CTA", pattern="link", signals=[], confidence="high",
                importance=3, safe=True, unsafe_reason=None, external=False, destination="/quote",
                selector="main > a:nth-of-type(2)", visible=True, dynamic=False, landmark="main",
                position={"x": 100, "y": 900}, aria={}, attributes={}, signature="cta|a|/quote")
    base.update(kw)
    return Interaction(**base)


def test_relocate_by_signature_when_dom_order_changed():
    # After reload a carousel added elements: old id p1e57 is now something else; the quote link is p1e61.
    fresh = {"elements": [
        {"id": "p1e57", "signature": "a|/reviews", "position": {"x": 0, "y": 880}, "visible": True},
        {"id": "p1e61", "signature": "a|/quote", "position": {"x": 100, "y": 905}, "visible": True},
    ]}
    assert relocate_element(_it(), fresh) == "p1e61"


def test_relocate_picks_nearest_of_repeated_links():
    fresh = {"elements": [
        {"id": "p1e3", "signature": "a|/quote", "position": {"x": 900, "y": 20}, "visible": True},   # header
        {"id": "p1e80", "signature": "a|/quote", "position": {"x": 110, "y": 890}, "visible": True},  # body CTA
    ]}
    assert relocate_element(_it(), fresh) == "p1e80"


def test_relocate_forms_and_missing():
    form = _it(tag="form", signature="form|form|https://www.example.com/send|contact", classification="form")
    fresh = {"elements": [], "forms": [{"id": "p1e200", "signature": "form|https://www.example.com/send|contact",
                                        "position": {"x": 0, "y": 0}}]}
    assert relocate_element(form, fresh) == "p1e200"
    assert relocate_element(_it(), {"elements": []}) is None


def test_time_limit_keeps_partial_results(journey_site):
    """A deadline that cuts the run short still returns the pages found so far."""
    from journey import run_customer_journey

    r = asyncio.run(run_customer_journey(site_url("/"), max_pages=20, depth="full", scan_id="pytest-deadline",
                                         deadline=time.monotonic() + 12))
    assert r.available, r.error
    assert r.pages, "pages scanned before the limit must be kept"
    assert r.error and "Time limit" in r.error or r.limits.get("scan_stopped_by_time_budget")


def test_unscored_audit_is_not_zero():
    from services.audit_service import _compute_overall_score

    assert _compute_overall_score({}) is None
    assert _compute_overall_score({"journey": 80}) == 80


def test_unscored_summary_text():
    from ai.executive_summary import generate_executive_summary

    text = asyncio.run(generate_executive_summary("https://www.axa.de", 0, {}, []))
    assert "could not be scored" in text and "0/100" not in text


def test_normalize_url_drops_campaign_parameters():
    from journey.journey_scanner import normalize_url
    assert normalize_url("https://www.axa.it/servizi/?utm_source=x&utm_medium=y#top") == "https://www.axa.it/servizi"
    assert normalize_url("https://www.axa.it/p?id=7&gclid=abc") == "https://www.axa.it/p?id=7"


def test_noise_events_are_not_interaction_tracking():
    from journey.journey_tracking import TrackedEvent
    for ev in ("gtag:get", "gtag:set", "OneTrustGroupsUpdated", "OptanonLoaded", "consent_update"):
        assert TrackedEvent(t=0, source="dataLayer", vendor="dataLayer", event=ev).is_lifecycle, ev
    assert not TrackedEvent(t=0, source="dataLayer", vendor="dataLayer", event="gtm.linkClick").is_lifecycle


def test_plain_button_is_not_a_cta():
    from journey.journey_interactions import CTA, classify
    from journey.journey_scanner import DiscoveredElement
    el = DiscoveredElement(id="e1", page_url="https://www.example.com/", tag="button", text="Carrozzerie",
                           landmark="main", style={}, attributes={"class": "chip"}, aria={})
    assert classify(el, {}, "www.example.com").kind != CTA
    styled = DiscoveredElement(id="e2", page_url="https://www.example.com/", tag="button", text="Get my price",
                               landmark="main", style={"has_background": True, "padded": True},
                               attributes={"class": "btn btn-primary"}, aria={})
    assert classify(styled, {}, "www.example.com").kind == CTA


def test_hung_page_is_skipped_and_tests_still_run(journey_site, monkeypatch):
    """One page that never finishes (seen on axa.it) must not use up the whole scan: it is
    skipped after the per-page limit, the other pages are scanned and interactions are tested."""
    from journey import journey_scanner, run_customer_journey

    real = journey_scanner.discover_page

    async def slow_discover(page, url, prefix):
        if url.rstrip("/").endswith("/resources"):
            await asyncio.sleep(3600)
        return await real(page, url, prefix)

    monkeypatch.setattr(journey_scanner, "discover_page", slow_discover)
    monkeypatch.setattr(journey_scanner, "PAGE_SCAN_TIMEOUT_S", 6.0)
    r = asyncio.run(run_customer_journey(site_url("/"), max_pages=6, depth="full", scan_id="pytest-hung-page",
                                         max_tested=3))
    hung = [p for p in r.pages if p["url"].rstrip("/").endswith("/resources")]
    assert hung and "did not finish loading" in (hung[0].get("error") or "")
    assert len(r.pages) >= 3
    assert any(i["tested"] for i in r.interactions)
