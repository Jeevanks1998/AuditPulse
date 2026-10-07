"""Sites whose tags are injected by JavaScript: other pages' raw HTML shows
nothing, which must count as "not verified", not "without analytics"."""

from analytics.analytics_score import PageAnalyticsResult, check_cross_page_consistency, compute_site_coverage


def _pages():
    home = PageAnalyticsResult(url="https://x.com/", trackers_detected=["TagCommander", "Piano Analytics"],
                               vendor_configs={"tagcommander": ["AXAcom"], "piano": ["641256"]})
    others = [PageAnalyticsResult(url=f"https://x.com/p{i}", not_verified=True) for i in range(5)]
    return [home] + others


def test_unverified_pages_are_not_counted_as_missing():
    pages = _pages()
    cross = check_cross_page_consistency(pages)
    cov = compute_site_coverage(pages, cross)
    assert cross == []
    assert cov["pages_without_analytics"] == 0
    assert cov["pages_not_verified"] == 5
    assert cov["pages_with_analytics_inconsistencies"] == 0


def test_really_missing_pages_still_flagged():
    pages = _pages()
    pages.append(PageAnalyticsResult(url="https://x.com/static"))   # checked, nothing there
    pages.append(PageAnalyticsResult(url="https://x.com/ok", trackers_detected=["TagCommander"],
                                     vendor_configs={"tagcommander": ["AXAcom"]}))
    cov = compute_site_coverage(pages, check_cross_page_consistency(pages))
    assert cov["pages_without_analytics"] == 1
