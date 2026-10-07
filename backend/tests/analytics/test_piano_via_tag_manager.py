"""
Piano Analytics loaded by a tag manager after consent (the axa.com setup):

  * the page ships only a TagCommander-style container, no Piano markup
  * a OneTrust-style banner renders late (3.5 s after load)
  * after "Accept", the container injects piano-analytics.js, which calls
    pa.setConfigurations({site, collectDomain}) and sends a hit to
    <id>.pa-cd.com/event?s=<site>&idclient=…

The analytics pass must wait for the late banner, accept it, wait for the
consent-gated tags, and then report Piano with its site id — not only the
tag manager.
"""

import asyncio
import os
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.journey.conftest import _free_port, patch_dns_and_browser

HOST = "www.piano-shop.com"
PIANO_SITE = "641256"
HITS = []

PAGE = """<!doctype html><html><head><title>Piano via tag manager</title>
<script>window.tc_vars = {page_name: 'home'};</script>
<script src="https://cdn.tagcommander.com/2149/tc_Shop_7.js"></script>
</head><body><main><h1>Insurance</h1><p>Hello.</p><a href="/about">About</a>
<div style="height:2000px"></div></main>
<script>
setTimeout(function () {
  var b = document.createElement('div');
  b.id = 'onetrust-banner-sdk';
  b.setAttribute('role', 'dialog');
  b.style.cssText = 'position:fixed;bottom:0;left:0;right:0;background:#fff;padding:20px';
  b.innerHTML = '<p>We use cookies to improve your experience and for analytics.</p>' +
    '<button id="onetrust-reject-all-handler">Reject All</button>' +
    '<button id="onetrust-accept-btn-handler">Accept All Cookies</button>';
  document.body.appendChild(b);
  document.getElementById('onetrust-accept-btn-handler').onclick = function () {
    b.remove();
    window.tC && window.tC.onConsent && window.tC.onConsent();
  };
}, 3500);
</script></body></html>"""

CONTAINER = """window.tC = { onConsent: function () {
  setTimeout(function () {
    var s = document.createElement('script');
    s.src = 'https://tag.aticdn.net/piano-analytics.js';
    s.id = 'tc_script_1';
    s.onload = function () {
      pa.setConfigurations({site: '%s', collectDomain: 'xnfwmvk.pa-cd.com'});
      pa.sendEvent('page.display', {page: 'home'});
    };
    document.body.appendChild(s);
  }, 1200);
}};""" % PIANO_SITE

PIANO_SDK = """window.pa = (function () {
  var cfg = {};
  return {
    setConfigurations: function (c) { for (var k in c) cfg[k] = c[k]; },
    getConfiguration: function (k) { return cfg[k]; },
    sendEvent: function (name, props) {
      var url = 'https://' + cfg.collectDomain + '/event?s=' + cfg.site + '&idclient=abc123';
      setTimeout(function () {
        fetch(url, {method: 'POST', body: JSON.stringify({events: [{name: name, data: props}]})}).catch(function () {});
      }, 900);
    }
  };
})();"""


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):  # noqa: N802
        host = (self.headers.get("Host") or "").split(":")[0]
        if host == "cdn.tagcommander.com":
            return self._send(200, "application/javascript", CONTAINER)
        if host == "tag.aticdn.net":
            return self._send(200, "application/javascript", PIANO_SDK)
        if host == HOST and self.path.split("?")[0] in ("/", "/about"):
            return self._send(200, "text/html; charset=utf-8", PAGE)
        if self.path == "/robots.txt":
            return self._send(200, "text/plain", "User-agent: *\nAllow: /\n")
        return self._send(404, "text/plain", "")

    def do_POST(self):  # noqa: N802
        HITS.append(((self.headers.get("Host") or "").split(":")[0], self.path))
        self._send(204, "text/plain", "")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()


@pytest.fixture(scope="module")
def piano_site():
    """One local HTTP server plays the site, the tag-manager CDN, the Piano CDN and the
    Piano collection endpoint (Chromium resolves every host to it)."""
    patch_dns_and_browser()
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield port
    srv.shutdown()


def _page_html(port: int) -> str:
    # Point the https:// script URLs at the local HTTP server.
    return PAGE.replace("https://cdn.tagcommander.com", f"http://cdn.tagcommander.com:{port}")


def test_piano_loaded_by_tag_manager_after_late_consent_is_reported(piano_site, monkeypatch):
    port = piano_site
    global PAGE, CONTAINER
    PAGE = _page_html(port)
    CONTAINER = CONTAINER.replace("https://tag.aticdn.net", f"http://tag.aticdn.net:{port}")
    globals()["PIANO_SDK"] = PIANO_SDK.replace("'https://' + cfg.collectDomain", f"'http://' + cfg.collectDomain + ':{port}'")

    real = socket.getaddrinfo

    def fake(host, *a, **k):
        name = host.decode() if isinstance(host, (bytes, bytearray)) else host
        if isinstance(name, str) and name.endswith("piano-shop.com"):
            host = "127.0.0.1"
        return real(host, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", fake)

    from analytics import analyze_site
    from crawler.parser import parse_html

    url = f"http://{HOST}:{port}/"
    result = asyncio.run(analyze_site(url, parse_html(url, PAGE), enable_runtime_checks=True))
    summary = result.summary
    configs = summary.vendor_configs

    assert "tagcommander" in configs
    assert "piano" in configs, (configs, getattr(result, "runtime_result", None) and result.runtime_result.consent_state)
    assert PIANO_SITE in configs["piano"]
    assert any(h[0] == "xnfwmvk.pa-cd.com" for h in HITS)
