"""AXA Italy pilot feedback on the Consent & Analytics report: dual GA4 tagging is consistent,
Microsoft Clarity that sends data is never "never fires", and one loader per GA4 ID is no duplicate."""

from analytics.analytics_score import PageAnalyticsResult, check_cross_page_consistency
from analytics.runtime import (AnalyticsRuntimeResult, CapturedRequest, _build_vendor_results,
                               check_runtime_analytics)


def _page(url, ga4):
    return PageAnalyticsResult(url=url, trackers_detected=["Google Analytics 4"], vendor_configs={"ga4": ga4})


def test_same_two_ga4_ids_on_every_page_is_consistent():
    pages = [_page("https://s/a", ["G-1", "G-2"]), _page("https://s/b", ["G-2", "G-1"])]
    found = check_cross_page_consistency(pages)
    assert not any(f["title"].startswith("Inconsistent") for f in found)
    assert any(f["severity"] == "info" and "2 properties" in f["title"] for f in found)


def test_different_ga4_ids_list_ids_and_pages():
    pages = [_page("https://s/a", ["G-1"]), _page("https://s/b", ["G-1"]), _page("https://s/c", ["G-9"])]
    f = next(f for f in check_cross_page_consistency(pages) if f["title"].startswith("Inconsistent"))
    assert f["severity"] == "warning"
    assert "G-1 on 2 of 3 page(s)" in f["description"] and "G-9 on 1 of 3 page(s) (https://s/c)" in f["description"]


def test_clarity_sending_data_is_not_never_fires():
    reqs = [CapturedRequest(url="https://a.clarity.ms/collect", phase="load", vendor_key="clarity",
                            event_name="session_event", is_page_view=False)]
    vendors = _build_vendor_results(reqs)
    assert vendors["clarity"].page_view_status == "passed"
    result = AnalyticsRuntimeResult(available=True, vendors=vendors)
    titles = [f["title"] for f in check_runtime_analytics(result, "https://s", {"clarity": True})]
    assert not any("never fires" in t for t in titles)
