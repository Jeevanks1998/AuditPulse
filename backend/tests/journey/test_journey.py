"""
Customer Journey tests.

Unit tests (no browser) for classification, then one live scan of the
fixture shop (tests/journey/site) asserting on discovery, classification,
safe testing, tracking validation, the journey map and QA findings.
"""

import asyncio

import pytest

from journey.journey_interactions import (
    CTA, DOWNLOAD, EMAIL, FORM_SUBMIT, LOGIN, NAVIGATION, PHONE, PURCHASE, SEARCH, SIGNUP, VIDEO, classify,
)
from journey.journey_scanner import DiscoveredElement, DiscoveredForm, is_stateful_url
from tests.journey.conftest import REQUEST_LOG, site_url

HOST = "www.example.com"


def el(**kw):
    base = dict(id="e1", page_url="https://www.example.com/", tag="a", text="", accessible_name="", landmark="main",
                style={}, attributes={}, aria={})
    base.update(kw)
    return DiscoveredElement(**base)


# ------------------------------------------------------------------ unit ---
@pytest.mark.parametrize("element,kind", [
    (el(destination="tel:+441234", text="Call"), PHONE),
    (el(destination="mailto:a@b.co", text="Mail"), EMAIL),
    (el(destination="https://www.example.com/a/report.pdf", text="Annual report"), DOWNLOAD),
    (el(destination="https://www.example.com/x", attributes={"download": ""}, text="Get it"), DOWNLOAD),
    (el(tag="video", destination="https://www.example.com/v.mp4"), VIDEO),
    (el(tag="iframe", destination="https://www.youtube.com/embed/abc"), VIDEO),
    (el(destination="https://www.example.com/about", text="About", landmark="nav"), NAVIGATION),
    (el(destination="https://www.example.com/anything", text="Discover more",
        style={"has_background": True, "padded": True, "bold": True, "font_size": 18}), CTA),
    (el(destination="https://www.example.com/account/login", text="My area"), LOGIN),
    (el(destination="https://www.example.com/register", text="Start"), SIGNUP),
    (el(tag="button", text="Add to basket"), PURCHASE),
    (el(tag="input", type="search", text=""), SEARCH),
])
def test_classification_is_signal_based(element, kind):
    c = classify(element, {}, HOST)
    assert c.kind == kind, (c.kind, c.signals)
    assert c.signals or kind in (PHONE, EMAIL)


def test_same_text_different_signals_different_class():
    """The label alone never decides: identical text, different structure."""
    styled = el(destination="https://www.example.com/p", text="Learn more",
                style={"has_background": True, "padded": True, "bold": True, "font_size": 18})
    plain_nav = el(destination="https://www.example.com/p", text="Learn more", landmark="nav")
    assert classify(styled, {}, HOST).kind == CTA
    assert classify(plain_nav, {}, HOST).kind == NAVIGATION


def test_form_submit_and_purchase_are_never_safe():
    form = DiscoveredForm(id="f1", page_url="https://www.example.com/c", fields=[{"type": "text", "name": "name"}])
    submit = el(id="b1", tag="button", type="submit", text="Send", form_id="f1")
    c = classify(submit, {"f1": form}, HOST)
    assert c.kind == FORM_SUBMIT and c.safe is False
    assert classify(el(tag="button", text="Buy now"), {}, HOST).safe is False
    assert classify(el(destination="https://www.example.com/logout", text="Sign out"), {}, HOST).safe is False


def test_stateful_urls_never_crawled():
    assert is_stateful_url("https://x.com/cart?add-to-cart=3")
    assert is_stateful_url("https://x.com/account/logout")
    assert not is_stateful_url("https://x.com/services/product")


# ------------------------------------------------------------- live scan ---
_RESULT = {}


def scan(site):
    if "r" not in _RESULT:
        from journey import run_customer_journey
        _RESULT["r"] = asyncio.run(run_customer_journey(site_url("/"), max_pages=20, depth="full", scan_id="pytest"))
    return _RESULT["r"]


def by_label(r, label):
    return next(i for i in r.interactions if i["label"] == label and i["duplicate_of"] is None)


def test_discovers_pages_and_relationships(journey_site):
    r = scan(journey_site)
    paths = {p["path"] for p in r.pages}
    assert {"/", "/services", "/services/product", "/resources", "/quote", "/contact", "/account/login"} <= paths
    product = next(p for p in r.pages if p["path"] == "/services/product")
    assert product["parent"] is not None          # discovered via a real link
    assert r.consent_state.startswith("accepted")


def test_dynamic_element_discovered(journey_site):
    r = scan(journey_site)
    it = by_label(r, "Explore the X200 pump")
    assert it["dynamic"] is True and it["classification"] == CTA


def test_safety_nothing_irreversible(journey_site):
    r = scan(journey_site)
    assert not [x for x in REQUEST_LOG if x[0] == "POST" and x[1] == "www.journey-shop.com"]   # no form submitted
    assert not [x for x in REQUEST_LOG if "cart" in x[2] or "checkout" in x[2]]               # cart link not followed
    assert by_label(r, "Buy now")["status"] == "skipped"
    assert by_label(r, "Send request")["status"] == "skipped"


def test_tracking_validation(journey_site):
    r = scan(journey_site)
    assert by_label(r, "Request a quote")["tracking"]["status"] == "not_tracked"          # the gap
    assert by_label(r, "Talk to sales")["tracking"]["status"] == "tracked"                # GA4 + dataLayer
    assert by_label(r, "Download brochure")["tracking"]["status"] == "tracked"
    assert by_label(r, "+1 555 123 4567")["tracking"]["status"] == "tracked"              # dataLayer push
    assert by_label(r, "Compare models")["tracking"]["status"] == "duplicate"
    assert by_label(r, "Request a quote (form)")["tracking"]["status"] == "tracked"       # form_start


def test_broken_and_inaccessible(journey_site):
    r = scan(journey_site)
    assert by_label(r, "See the offer")["outcome"] == "broken_destination"
    old = by_label(r, "Old catalogue")
    assert old["status"] == "failed" and old["http_status"] == 404
    assert by_label(r, "Specs sheet")["http_status"] == 200


def test_screenshots_before_highlighted_after(journey_site):
    import os
    from config.settings import settings

    r = scan(journey_site)
    shots = by_label(r, "Request a quote")["screenshots"]
    for k in ("before", "highlighted", "after"):
        assert shots.get(k) and os.path.exists(os.path.join(settings.SCREENSHOT_DIR, shots[k]))
    assert "/journey/pytest/" in "/" + shots["before"]


def test_journey_map_and_findings(journey_site):
    r = scan(journey_site)
    nodes = r.journey_map["nodes"]
    quote = next(j for j in r.journey_map["journeys"] if j["name"].endswith("Request a quote"))
    labels = [nodes[s].get("path") if s.startswith("page:") else nodes[s]["label"] for s in quote["steps"]]
    assert labels[:4] == ["/", "Request a quote", "/quote", "Request a quote (form)"]
    titles = [f["title"] for f in r.findings]
    assert "No analytics detected for conversion interaction: Request a quote" in titles
    assert "Broken important CTA: See the offer" in titles
    assert "Download inaccessible: Old catalogue" in titles
    assert "Duplicate event: Compare models" in titles
    h = r.health["counts"]
    assert h["tracking_gaps"] >= 2 and h["forms"] == 3 and h["downloads"] == 3
    assert r.health["score"] is not None
