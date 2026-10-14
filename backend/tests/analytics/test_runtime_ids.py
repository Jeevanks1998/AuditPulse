"""IDs come from what the browser saw, not only the page code (the axa.de case:
Meta, LinkedIn and GA4 are fired by GTM, so the HTML holds none of their IDs)."""

from analytics import runtime_vendor_ids
from analytics.runtime import AnalyticsRuntimeResult, VendorRuntimeResult, _classify


def test_ga4_hit_on_any_collect_host():
    for url in ("https://stats.g.doubleclick.net/g/collect?v=2&tid=G-X70K9LDP0J&en=page_view",
                "https://sgtm.example.com/g/collect?v=2&tid=G-ABC123&en=page_view"):
        r = _classify(url)
        assert r and r.vendor_key == "ga4" and r.identifier.startswith("G-")
    assert _classify("https://analytics.google.com/g/collect?a=adblocker_check") is None


def test_first_party_gtm_container():
    r = _classify("https://data.example.com/gtm.js?id=GTM-XYZ12")
    assert r and r.vendor_key == "gtm" and r.identifier == "GTM-XYZ12"


def test_ids_from_requests_and_page_globals():
    rt = AnalyticsRuntimeResult(available=True)
    rt.vendors = {
        "meta_pixel": VendorRuntimeResult("meta_pixel", "Meta", request_urls=[
            "https://www.facebook.com/tr/?id=386519035982041&ev=PageView",
            "https://www.facebook.com/tr/?id=1455994128719209&ev=PageView"]),
        "linkedin": VendorRuntimeResult("linkedin", "LinkedIn", request_urls=[
            "https://px.ads.linkedin.com/collect?v=2&fmt=js&pid=2923529"]),
    }
    rt.page_globals = {"google_tag_ids": ["GTM-W9WSTRG", "G-X70K9LDP0J", "AW-1022972001", "DC-8166547"],
                       "tagcommander": False}
    ids = runtime_vendor_ids(rt)
    assert ids["meta_pixel"] == ["386519035982041", "1455994128719209"]
    assert ids["linkedin"] == ["2923529"]
    assert ids["gtm"] == ["GTM-W9WSTRG"] and ids["ga4"] == ["G-X70K9LDP0J"]
    assert "tagcommander" not in ids
