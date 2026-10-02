"""
Test harness for the consent scanner.

Serves the HTML fixtures in ./fixtures from a local HTTP server and makes
Chromium resolve *every* hostname to 127.0.0.1, so the fixture pages can
use realistic hosts (www.example-shop.de, www.googletagmanager.com,
cdn.privacy-mgmt.com, …) without touching the network. Request
classification only looks at hostname + path, so plain http on a local
port exercises exactly the same code paths as production.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("SCREENSHOT_DIR", tempfile.mkdtemp(prefix="ap-shots-"))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SITES = {
    "www.example-shop.de": ("eu_onetrust.html", ["XSRF-TOKEN=abc; Path=/", "session=xyz; Path=/; HttpOnly"]),
    "www.globalco.com": ("global_bad.html", []),
    "news.example.in": ("iframe_cmp.html", []),
    "cdn.privacy-mgmt.com": ("cmp.html", []),
    "shop.example.co.uk": ("ack_only.html", []),
    "plain.example.com": ("no_banner.html", []),
    "boutique.example.fr": ("continue_only.html", []),
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = _free_port()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def do_GET(self):  # noqa: N802
        host = (self.headers.get("Host") or "").split(":")[0]
        site = SITES.get(host)
        if site and self.path.split("?")[0] in ("/", "/index.html", "/cmp.html"):
            body = (FIXTURES / site[0]).read_text().replace("PORT", str(PORT)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            for c in site[1]:
                self.send_header("Set-Cookie", c)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # Any tracker / vendor endpoint: empty JS or 1x1 response.
        is_js = self.path.split("?")[0].endswith(".js")
        body = b"/* ok */" if is_js else b""
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript" if is_js else "image/gif")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="session")
def site_server():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield PORT
    server.shutdown()


@pytest.fixture(scope="session", autouse=True)
def _route_all_hosts_to_localhost():
    """Every Chromium launched by consent/* resolves all hosts to the fixture server."""
    try:
        from playwright.async_api._generated import BrowserType
    except ImportError:
        yield
        return
    original = BrowserType.launch

    async def launch(self, *args, **kwargs):
        extra = ["--host-resolver-rules=MAP * 127.0.0.1, EXCLUDE localhost", "--no-proxy-server"]
        kwargs["args"] = list(kwargs.get("args") or []) + extra
        kwargs.setdefault("proxy", None)
        return await original(self, *args, **kwargs)

    BrowserType.launch = launch
    os.environ["NO_PROXY"] = "*"
    yield
    BrowserType.launch = original


def site_url(host: str) -> str:
    return f"http://{host}:{PORT}/"


def fetch(host: str):
    """Static fetch of a fixture page: (html, set-cookie header values)."""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    conn.request("GET", "/", headers={"Host": f"{host}:{PORT}"})
    resp = conn.getresponse()
    html = resp.read().decode()
    cookies = resp.headers.get_all("Set-Cookie") or []
    conn.close()
    return html, cookies


def chromium_available() -> bool:
    try:
        import asyncio
        from playwright.async_api import async_playwright

        async def _probe():
            async with async_playwright() as pw:
                b = await pw.chromium.launch()
                await b.close()
        asyncio.run(_probe())
        return True
    except Exception:  # noqa: BLE001
        return False
