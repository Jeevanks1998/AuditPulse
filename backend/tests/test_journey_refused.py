"""Journey Map: page loads refused by bot protection are recognised (and retried / worked around)."""

from journey.browser_session import JourneyBrowser, is_browser_dead_error, is_refused_error


def test_refused_errors_recognised():
    msg = "Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.axa.de/"
    assert is_refused_error(msg)
    assert is_refused_error("net::ERR_CONNECTION_RESET")
    assert not is_refused_error("Element no longer present after reloading the page.")
    assert not is_browser_dead_error(msg)  # not a crash: don't burn browser restarts on it


def test_extra_args_default_empty():
    assert JourneyBrowser().extra_args == []
