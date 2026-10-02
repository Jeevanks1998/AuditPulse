"""
Full-application end-to-end check for the Customer Journey module.

Real API + real database + real audit pipeline + Playwright, against the
local fixture shop (tests/journey/site), then the real report.html and
dashboard.html in a browser:

  1. start the fixture shop, the frontend (static) and the API (uvicorn)
  2. log in, POST /api/v1/audits/ with modules ["journey", "consent"], depth=full
  3. GET /audits/{id}/journey and assert on discovery, safety, tracking,
     map and findings
  4. export.json / PDF / evidence.zip (evidence/journey/<page>/interaction_*.png)
  5. open report.html#journey and dashboard.html, click a map step, screenshot

Usage (from backend/):
    DATABASE_URL=postgresql+asyncpg://user:pass@127.0.0.1:5432/db \\
        python -m tests.journey.run_full_app_e2e --out /tmp/ap-journey-e2e
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
FRONTEND = BACKEND.parent
sys.path.insert(0, str(BACKEND))

_ARGS = argparse.ArgumentParser()
_ARGS.add_argument("--out", default=tempfile.mkdtemp(prefix="ap-journey-e2e-"))
ARGS = _ARGS.parse_args()
OUT = Path(ARGS.out)
OUT.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("SCREENSHOT_DIR", str(OUT / "screenshots"))
os.environ.setdefault("REPORTS_DIR", str(OUT / "reports"))
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")
os.environ.setdefault("RATE_LIMIT_REQUESTS", "5000")
os.environ["CRAWLER_ENABLE_RUNTIME_CHECKS"] = "true"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


API_PORT, WEB_PORT = _free_port(), _free_port()
os.environ["CORS_ORIGINS_RAW"] = f"http://127.0.0.1:{WEB_PORT},http://localhost:{WEB_PORT}"

from tests.journey import conftest as fx  # noqa: E402

fx.patch_dns_and_browser()

CHECKS, FAILED = [], []


def check(name, ok, detail=""):
    CHECKS.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("  PASS " if ok else "  FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def start_frontend():
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(FRONTEND), **k)

        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] == "/assets/js/env.js":
                body = f"window.__AUDITPULSE_API_BASE__ = 'http://127.0.0.1:{API_PORT}/api/v1';".encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return super().do_GET()

    srv = ThreadingHTTPServer(("127.0.0.1", WEB_PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def start_api():
    import uvicorn
    from main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=API_PORT, log_level="warning", loop="asyncio"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", API_PORT), timeout=0.2):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("API did not start")


async def ensure_user(email, password):
    import secrets
    from passlib.context import CryptContext
    from sqlalchemy import select

    import models  # noqa: F401
    from config.database import AsyncSessionLocal, init_db
    from models.user import User

    await init_db()
    async with AsyncSessionLocal() as db:
        if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none() is None:
            db.add(User(name="Journey Admin", email=email, hashed_password=CryptContext(schemes=["bcrypt"]).hash(password),
                        api_key=secrets.token_hex(16), role="Admin", is_active=True, auditpulse_access=True))
            await db.commit()


def main() -> int:
    import httpx

    fx.start_server()
    start_frontend()
    email, password = "journey-e2e@example.com", "Journey-pass-1234"
    asyncio.run(ensure_user(email, password))
    start_api()
    api = lambda m, p, **kw: client.request(m, f"http://127.0.0.1:{API_PORT}/api/v1{p}", **kw)  # noqa: E731

    client = httpx.Client(timeout=180, trust_env=False)
    login = api("POST", "/auth/login", json={"email": email, "password": password})
    check("login", login.status_code == 200, login.text[:200])
    token = login.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"

    print("\n== audit with Customer Journey (depth=full)")
    r = api("POST", "/audits/", json={"url": fx.site_url("/"), "modules": ["journey", "consent"], "depth": "full", "max_pages": 20})
    check("audit accepted with 'journey' module", r.status_code == 202, r.text[:200])
    audit_id = r.json()["id"]
    steps_seen = set()
    for _ in range(600):
        p = api("GET", f"/audits/{audit_id}/progress").json()
        steps_seen.add(p.get("current_step"))
        if p["status"] in ("completed", "failed"):
            break
        time.sleep(1)
    check("audit completed", p["status"] == "completed", json.dumps(p))
    check("progress reported the checkJourney step", "checkJourney" in steps_seen, str(steps_seen))

    j = api("GET", f"/audits/{audit_id}/journey").json()
    v = j.get("report_view") or {}
    (OUT / "journey_api.json").write_text(json.dumps(j, indent=1, default=str)[:3_000_000])
    c = v.get("counts") or {}
    check("journey available", v.get("available") is True, str(v.get("error")))
    check("pages scanned >= 7", c.get("pages_scanned", 0) >= 7, str(c))
    check("interactions discovered >= 25", c.get("interactions_discovered", 0) >= 25, str(c))
    check("interactions tested >= 15", c.get("interactions_tested", 0) >= 15, str(c))
    check("forms = 3, downloads = 3", c.get("forms") == 3 and c.get("downloads") == 3, str(c))
    rows = {x["label"]: x for x in v.get("interactions") or []}
    check("gap: 'Request a quote' tested, not tracked",
          rows["Request a quote"]["test_status"] == "success" and rows["Request a quote"]["tracking_status"] == "not_tracked")
    check("'Talk to sales' tracked", rows["Talk to sales"]["tracking_status"] == "tracked")
    check("'Buy now' not executed (safety)", rows["Buy now"]["test_status"] == "skipped")
    check("form submit not executed", rows["Send request"]["test_status"] == "skipped")
    check("no form POST reached the site", not [x for x in fx.REQUEST_LOG if x[0] == "POST" and x[1] == fx.HOST])
    check("before/highlighted/after screenshots for 'Request a quote'",
          all(rows["Request a quote"]["screenshots"].get(k) for k in ("before", "highlighted", "after")))
    shot = client.get(f"http://127.0.0.1:{API_PORT}{rows['Request a quote']['screenshots']['highlighted']}")
    check("screenshot served by /screenshots", shot.status_code == 200 and shot.content[:4] == b"\x89PNG", str(shot.status_code))
    journeys = (v.get("map") or {}).get("journeys") or []
    check("journey map has the quote journey", any(x["name"].endswith("Request a quote") for x in journeys))
    titles = [f["title"] for f in v.get("findings") or []]
    check("finding: conversion not tracked", "Conversion interaction not tracked: Request a quote" in titles)
    check("finding: broken CTA", "Broken important CTA: See the offer" in titles)

    audit = api("GET", f"/audits/{audit_id}").json()
    check("journey score in audit breakdown", "journey" in (audit.get("breakdown") or {}), str(audit.get("breakdown")))
    rep = api("GET", f"/reports/{audit_id}")
    check("journey findings in the report's findings list",
          rep.status_code == 200 and any(f.get("module") == "journey" for f in rep.json().get("findings") or []),
          f"{rep.status_code} {rep.text[:200]}")

    exp = api("GET", f"/reports/{audit_id}/export.json")
    check("export.json has journey_view", exp.status_code == 200 and bool(exp.json().get("journey_view")))
    pdf = api("GET", f"/reports/{audit_id}/export")
    ok_pdf = pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    check("PDF export", ok_pdf, str(pdf.status_code))
    if ok_pdf:
        (OUT / "report.pdf").write_bytes(pdf.content)
    z = api("GET", f"/reports/{audit_id}/evidence.zip")
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist() if z.status_code == 200 else []
    (OUT / "evidence.zip").write_bytes(z.content)
    check("evidence.zip has evidence/journey/<page>/interaction_*_before/after/highlighted.png",
          any(n.startswith("evidence/journey/") and n.endswith("_before.png") for n in names)
          and any(n.endswith("_highlighted.png") for n in names) and any(n.endswith("_after.png") for n in names),
          str(names[:10]))

    print("\n== frontend")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-proxy-server"])
        ctx = b.new_context(viewport={"width": 1440, "height": 1000})
        session = json.dumps({"token": token, "user": login.json()["user"]})
        ctx.add_init_script("window.sessionStorage.setItem('auditpulse:session', %s);" % json.dumps(session))
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{WEB_PORT}/report.html?id={audit_id}#journey")
        try:
            page.wait_for_selector("#journeyMap .jr-step", timeout=30_000)
            rendered = True
        except Exception:  # noqa: BLE001
            rendered = False
        check("report.html renders the Customer Journey section", rendered, "; ".join(errors[-3:]))
        page.evaluate("document.querySelectorAll('#journey details').forEach(d => d.open = true)")
        step = page.query_selector("#journeyMap .jr-step[data-tracking='not_tracked']")
        if step:
            step.click()
            page.wait_for_timeout(600)
        detail = page.inner_text("#journeyDetail") if rendered else ""
        check("clicking a gap step shows its evidence", "Not detected" in detail and "Successfully tested" in detail, detail[:200])
        page.wait_for_timeout(1500)
        el = page.query_selector("#journey")
        if el:
            el.screenshot(path=str(OUT / "report_journey.png"))
        page.goto(f"http://127.0.0.1:{WEB_PORT}/audit.html")
        page.wait_for_timeout(1500)
        check("audit.html offers the Customer Journey module", page.query_selector("input[data-module='journey']") is not None)
        page.goto(f"http://127.0.0.1:{WEB_PORT}/dashboard.html")
        try:
            page.wait_for_selector("#journeyHealthCard .jr-tile", timeout=20_000)
            dash = True
        except Exception:  # noqa: BLE001
            dash = False
        check("dashboard shows the Customer Journey card", dash)
        page.wait_for_timeout(1000)
        page.screenshot(path=str(OUT / "dashboard.png"), full_page=True)
        check("no JavaScript errors", not errors, "; ".join(errors[:3]))
        b.close()

    (OUT / "e2e_summary.json").write_text(json.dumps({"audit_id": audit_id, "checks": CHECKS, "counts": c,
                                                      "score": v.get("score")}, indent=2))
    print(f"\n{len(CHECKS) - len(FAILED)}/{len(CHECKS)} checks passed. Output: {OUT}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
