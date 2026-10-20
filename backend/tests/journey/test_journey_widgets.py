"""
Real-site widget behaviour seen on axa.it, reproduced on a fixture page:

  * a link with target=_blank opens a new tab — it works, it is not "broken";
  * slider arrows (slick) are page UI: never a CTA / conversion, never a gap;
  * the already-active tab is not clicked; another tab that swaps the list
    (same size, same text length) is detected as working;
  * a styled button that really does nothing is still reported as not working.
"""

import asyncio

import pytest

from tests.journey.conftest import site_url

_R = {}


def scan(_site):
    if "r" not in _R:
        from journey import run_customer_journey
        _R["r"] = asyncio.run(run_customer_journey(site_url("/widgets"), max_pages=1, depth="homepage",
                                                   scan_id="pytest-widgets"))
    return _R["r"]


def _by_label(r, label):
    return next(i for i in r.interactions if i["label"] == label and i["page_url"].endswith("/widgets"))


def test_new_tab_link_is_working(journey_site):
    r = scan(journey_site)
    it = _by_label(r, "Open the offer")
    assert it["status"] == "success" and it["outcome"] == "opened_new_tab", it["observed"]
    assert "/quote" in (it["final_url"] or "")
    assert not any("Open the offer" in f["title"] and "does not work" in f["title"] for f in r.findings)


def test_carousel_arrows_are_not_ctas(journey_site):
    r = scan(journey_site)
    for label in ("Previous", "Next"):
        it = _by_label(r, label)
        assert it["classification"] == "other" and it["pattern"] == "carousel", (label, it["classification"])
        assert not it["tested"]
    assert not any("Next" in f["title"] or "Previous" in f["title"] for f in r.findings)


def test_tabs(journey_site):
    r = scan(journey_site)
    active = _by_label(r, "Body shops")
    assert active["pattern"] == "tab" and not active["tested"]
    other = _by_label(r, "Glass")
    assert other["pattern"] == "tab"
    assert other["status"] == "success", other["observed"]


def test_dead_button_still_reported(journey_site):
    r = scan(journey_site)
    dead = _by_label(r, "Get my price")
    assert dead["tested"] and dead["status"] == "failed" and dead["outcome"] == "no_visible_effect"
