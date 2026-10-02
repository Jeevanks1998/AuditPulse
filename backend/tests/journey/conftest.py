"""
Fixture website for the Customer Journey tests: a small multi-page shop
(www.journey-shop.com) served locally; every hostname resolves to the
fixture server inside Chromium (same technique as tests/consent).
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
os.environ.setdefault("SCREENSHOT_DIR", tempfile.mkdtemp(prefix="ap-journey-shots-"))

SITE = Path(__file__).resolve().parent / "site"
HOST = "www.journey-shop.com"
ROUTES = {
    "/": "index.html", "/services": "services.html", "/services/product": "product.html",
    "/resources": "resources.html", "/quote": "quote.html", "/contact": "contact.html",
    "/account/login": "login.html",
}
FILES = {"/files/brochure.pdf": ("application/pdf", b"%PDF-1.4\n% fixture\n"),
         "/files/specs.docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK\x03\x04docx")}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = int(os.environ.get("JOURNEY_FIXTURE_PORT") or _free_port())
REQUEST_LOG: list = []


def render(name: str) -> bytes:
    html = (SITE / name).read_text()
    html = html.replace("@@HEADER@@", (SITE / "_header.html").read_text())
    html = html.replace("@@BANNER@@", (SITE / "_banner.html").read_text())
    return html.replace("PORT", str(PORT)).encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body, head=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _route(self, head=False):
        host = (self.headers.get("Host") or "").split(":")[0]
        path = self.path.split("?")[0]
        REQUEST_LOG.append((self.command, host, self.path))
        if host != HOST:
            body = b"" if not path.endswith(".js") else b"/* ok */"
            return self._send(200, "application/javascript" if path.endswith(".js") else "image/gif", body, head)
        if path in ROUTES:
            return self._send(200, "text/html; charset=utf-8", render(ROUTES[path]), head)
        if path in ("/_common.js",):
            return self._send(200, "application/javascript", (SITE / "_common.js").read_text().replace("PORT", str(PORT)).encode(), head)
        if path == "/_style.css":
            return self._send(200, "text/css", (SITE / "_style.css").read_bytes(), head)
        if path in FILES:
            ctype, body = FILES[path]
            return self._send(200, ctype, body, head)
        if path.startswith("/media/"):
            return self._send(200, "video/mp4", b"", head)
        if path == "/robots.txt":
            return self._send(200, "text/plain", b"User-agent: *\nAllow: /\n", head)
        return self._send(404, "text/html", b"<h1>Not found</h1>", head)

    def do_GET(self):  # noqa: N802
        self._route()

    def do_HEAD(self):  # noqa: N802
        self._route(head=True)

    def do_POST(self):  # noqa: N802
        REQUEST_LOG.append(("POST", (self.headers.get("Host") or "").split(":")[0], self.path))
        self._send(200, "text/plain", b"posted")


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def site_url(path: str = "/") -> str:
    return f"http://{HOST}:{PORT}{path}"


def patch_dns_and_browser():
    """Resolve fixture hosts locally for Python (httpx) and Chromium."""
    real = socket.getaddrinfo

    def fake(host, *a, **k):
        name = host.decode() if isinstance(host, (bytes, bytearray)) else host
        if isinstance(name, str) and (name.endswith("journey-shop.com") or name.endswith("google-analytics.com")
                                      or name == "external.example.org"):
            host = "127.0.0.1"
        return real(host, *a, **k)

    socket.getaddrinfo = fake
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(var, None)
    os.environ["NO_PROXY"] = "*"
    from playwright.async_api._generated import BrowserType

    if getattr(BrowserType.launch, "_ap_patched", False):
        return
    orig = BrowserType.launch

    async def launch(self, *a, **k):
        k["args"] = list(k.get("args") or []) + ["--host-resolver-rules=MAP * 127.0.0.1, EXCLUDE localhost",
                                                 "--no-proxy-server"]
        return await orig(self, *a, **k)

    launch._ap_patched = True
    BrowserType.launch = launch


@pytest.fixture(scope="session")
def journey_site():
    patch_dns_and_browser()
    srv = start_server()
    yield site_url("/")
    srv.shutdown()
