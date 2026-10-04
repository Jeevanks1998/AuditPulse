"""Durable screenshots (keys, compression) and the consent controls filter."""

import io

from PIL import Image

from reports.consent_view import build_consent_view
from utils.screenshot_store import _compress, collect_screenshot_urls, key_from_url, safe_key


def test_keys_are_safe_and_match_urls():
    assert key_from_url("/screenshots/journey/a1/home/interaction_001_before.png") == "journey/a1/home/interaction_001_before.png"
    assert key_from_url("https://api.example.test/screenshots/site_banner.png?x=1") == "site_banner.png"
    assert safe_key("../main.py") is None and safe_key("journey/../../etc/passwd") is None
    assert safe_key("") is None


def test_compress_shrinks_and_keeps_jpeg_readable():
    buf = io.BytesIO()
    Image.new("RGBA", (2400, 12000), (255, 0, 0, 255)).save(buf, "PNG")
    data, ctype = _compress(buf.getvalue())
    assert ctype == "image/jpeg"
    im = Image.open(io.BytesIO(data))
    assert im.width == 1280 and im.height <= 8000


def test_collects_urls_from_nested_payload():
    payload = {"consent_view": {"screenshots": [{"url": "/screenshots/a.png"}]},
               "journey_view": {"interactions": [{"screenshots": {"before": "/screenshots/journey/x/b.png"}}]},
               "other": "not a screenshot"}
    assert collect_screenshot_urls(payload) == {"/screenshots/a.png", "/screenshots/journey/x/b.png"}


def test_only_classified_consent_controls_are_listed():
    ctr = [{"label": l, "action": a, "layer": ly, "evidence": "Rendered consent banner"} for l, a, ly in [
        ("Consult our partners", "unclassified", 1), ("Reject all", "reject_all", 1), ("Accept all", "accept_all", 1),
        ("Close preference center", "unclassified", 2), ("Reject all", "reject_all", 2), ("Reject all", "reject_all", 2)]]
    view = build_consent_view({"has_cookie_banner": True, "technical_scan": {"controls": ctr}})
    assert [(c["label"], c["layer"]) for c in view["controls"]] == [("Reject all", 1), ("Accept all", 1), ("Reject all", 2)]
    assert view["controls_hidden"] == {"count": 2, "examples": ["Consult our partners", "Close preference center"]}
