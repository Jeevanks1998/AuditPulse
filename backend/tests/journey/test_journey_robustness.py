"""
Robustness of the Customer Journey scan on real-world sites:

  * elements are found again by what they are (signature), not by their
    DOM-order number, which changes between two loads of the same page
    (axa.it: order differed from element #274 on);
  * a time limit keeps everything already found instead of returning nothing
    ("The journey map scan could not run: unknown error" on axa.de);
  * an audit where no module produced a score is "not scored", not 0/100.
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
    # After reload a carousel added elements before it: the old id p1e57 is now
    # a different element; the quote link is p1e61.
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
