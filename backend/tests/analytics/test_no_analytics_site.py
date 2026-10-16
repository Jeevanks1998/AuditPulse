"""A site with a cookie banner but no analytics at all (the axa-lifeeurope.com
case): the score must not read 100 / Healthy, and the banner's own dataLayer
bookkeeping (OneTrustLoaded…) is not an analytics data layer."""

import asyncio
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.journey.conftest import _free_port, patch_dns_and_browser

HOST = "www.no-analytics-example.com"
PAGE = """<!doctype html><html><head><title>No analytics</title>
<script>window.dataLayer = window.dataLayer || []; dataLayer.push({event: 'OneTrustLoaded', OnetrustActiveGroups: ',C0001,'});</script>
</head><body><main><h1>Insurance</h1></main>
<script>
setTimeout(function () {
  var b = document.createElement('div'); b.id = 'onetrust-banner-sdk';
  b.style.cssText = 'position:fixed;bottom:0;left:0;right:0;background:#fff;padding:20px';
  b.innerHTML = '<p>We use cookies for audience measurement.</p><button id="onetrust-reject-all-handler">Reject Non-Essential Cookies</button>' +
                '<button id="onetrust-accept-btn-handler">Accept Non-Essential Cookies</button>';
  document.body.appendChild(b);
  document.getElementById('onetrust-accept-btn-handler').onclick = function () {
    dataLayer.push({event: 'OneTrustGroupsUpdated', OnetrustActiveGroups: ',C0001,C0002,'}); b.remove(); };
}, 800);
</script></body></html>"""


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        body = (PAGE if self.path.split("?")[0] == "/" else "").encode()
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_no_analytics_is_not_healthy(monkeypatch):
    patch_dns_and_browser()
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = socket.getaddrinfo

    def fake(host, *a, **k):
        name = host.decode() if isinstance(host, (bytes, bytearray)) else host
        if isinstance(name, str) and name.endswith("no-analytics-example.com"):
            host = "127.0.0.1"
        return real(host, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    try:
        from analytics import analyze_site
        from crawler.parser import parse_html

        url = f"http://{HOST}:{port}/"
        r = asyncio.run(analyze_site(url, parse_html(url, PAGE), enable_runtime_checks=True))
        assert r.summary.trackers_detected == []
        assert r.score.overall == 0 and r.summary.analytics_score == 0
        assert any(f["title"] == "No analytics tracking found" and f["severity"] == "critical" for f in r.findings)
        assert r.summary.data_layer_present is False      # only OneTrust bookkeeping in dataLayer
    finally:
        srv.shutdown()
