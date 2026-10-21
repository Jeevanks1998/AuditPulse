"""Bot-protection block pages are recognised and reported as 'blocked', never scored as the website."""

import asyncio
import http.server
import threading

from utils.bot_block import block_finding, browser_preflight, detect_block

INCAPSULA = ('<html style="height:100%"><head><META NAME="ROBOTS" CONTENT="NOINDEX, NOFOLLOW"></head><body>'
             '<iframe id="main-iframe" src="/_Incapsula_Resource?SWUDNSAI=31&xinfo=17-1&incident_id=2100000800114114745-149649884934575121'
             '&edet=12&cinfo=0e0000001edc&cip=152.55.188.34&mth=GET" frameborder=0>Request unsuccessful. Incapsula incident ID: '
             '2100000800114114745-149649884934575121</iframe></body></html>')


def test_incapsula_page_detected_with_incident_and_ip():
    b = detect_block(INCAPSULA)
    assert b.blocked and b.vendor == "Imperva (Incapsula)"
    assert b.incident_id == "2100000800114114745-149649884934575121"
    assert b.client_ip == "152.55.188.34"


def test_cloudflare_challenge_detected():
    assert detect_block("<html><head><title>Just a moment...</title></head><body>cf-chl-widget</body></html>").blocked


def test_normal_page_not_blocked():
    html = "<html><head><title>AXA Ireland</title></head><body>" + "".join(
        f'<a href="/p{i}">Access denied help {i}</a>' for i in range(40)) + "</body></html>"
    assert not detect_block(html, "AXA Ireland").blocked


def test_block_finding_and_summary():
    b = detect_block(INCAPSULA)
    f = block_finding("https://www.axa.ie", b)
    assert f["severity"] == "critical" and "Imperva" in f["title"] and "152.55.188.34" in f["description"]
    from ai.executive_summary import generate_executive_summary
    text = asyncio.run(generate_executive_summary("https://www.axa.ie", 0, {}, [f]))
    assert "bot protection blocked" in text and "0/100" not in text


def test_browser_preflight_sees_block_page():
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            body = INCAPSULA.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        b = asyncio.run(browser_preflight(f"http://127.0.0.1:{srv.server_address[1]}/", "pytest-block", wait_s=3))
    finally:
        srv.shutdown()
    assert b.checked and b.blocked and b.vendor == "Imperva (Incapsula)", b
