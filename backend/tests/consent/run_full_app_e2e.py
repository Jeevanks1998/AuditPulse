"""
Full-application end-to-end check for the Consent module (Phases 1–4).

Runs the *real* app — FastAPI + the real database + the real audit
pipeline + Playwright — against the local fixture sites in ./fixtures,
then drives the real report.html / dashboard.html in a browser:

    1. start the fixture web server (all fixture hosts -> 127.0.0.1)
    2. start the API (uvicorn, in-process) on the configured DATABASE_URL
    3. create a test user, log in through POST /api/v1/auth/login
    4. POST /api/v1/audits/ with modules=["consent"] for each fixture site
       (+ one with ["consent", "analytics"]), wait for completion
    5. GET /audits/{id}/consent, /reports/{id}/export.json,
       /reports/{id}/export (PDF), /reports/{id}/evidence.zip — and assert
       on what came back
    6. re-run one site and prove the second scan is fresh
    7. open report.html#consent and dashboard.html in Chromium with the
       session token, wait for the consent UI, and save screenshots

Usage (from backend/):
    DATABASE_URL=postgresql+asyncpg://user:pass@127.0.0.1:5432/db \\
        python -m tests.consent.run_full_app_e2e [--out DIR]

Exit code 0 = every check passed. Output: a JSON summary + PNGs in --out.
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
_ARGS.add_argument("--out", default=tempfile.mkdtemp(prefix="ap-e2e-"))
ARGS = _ARGS.parse_args()
OUT = Path(ARGS.out)
OUT.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("SCREENSHOT_DIR", str(OUT / "screenshots"))
os.environ.setdefault("REPORTS_DIR", str(OUT / "reports"))
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")  # unreachable -> in-memory rate limiter
os.environ["CRAWLER_ENABLE_RUNTIME_CHECKS"] = "true"
# One test client polls progress and loads many pages from one IP; the
# production 100 req/min/IP limit would throttle the harness itself.
os.environ.setdefault("RATE_LIMIT_REQUESTS", "5000")
os.environ.setdefault("ANTHROPIC_API_KEY", "")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


API_PORT = _free_port()
WEB_PORT = _free_port()
os.environ["CORS_ORIGINS_RAW"] = f"http://127.0.0.1:{WEB_PORT},http://localhost:{WEB_PORT}"

from tests.consent import conftest as fx  # noqa: E402  (fixture sites + PORT)

FIXTURE_HOSTS = set(fx.SITES) | {
    "www.googletagmanager.com", "www.google-analytics.com", "www.facebook.com", "cdn.privacy-mgmt.com",
}

# --- make the backend's own HTTP fetch resolve fixture hosts locally --------
_real_getaddrinfo = socket.getaddrinfo


def _getaddrinfo(host, *a, **k):
    name = host.decode() if isinstance(host, (bytes, bytearray)) else host
    if isinstance(name, str) and name in FIXTURE_HOSTS:
        host = "127.0.0.1"
    return _real_getaddrinfo(host, *a, **k)


socket.getaddrinfo = _getaddrinfo
for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(var, None)
os.environ["NO_PROXY"] = "*"

# --- make every Chromium the app launches resolve fixture hosts locally -----
from playwright.async_api._generated import BrowserType  # noqa: E402

_orig_launch = BrowserType.launch


async def _launch(self, *a, **k):
    k["args"] = list(k.get("args") or []) + [
        "--host-resolver-rules=MAP * 127.0.0.1, EXCLUDE localhost", "--no-proxy-server"]
    return await _orig_launch(self, *a, **k)


BrowserType.launch = _launch

RESULTS: dict = {"checks": [], "audits": {}}
FAILED: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
    print(("  PASS " if ok else "  FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def start_fixture_server() -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", fx.PORT), fx._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def start_frontend_server() -> None:
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


def start_api() -> None:
    import uvicorn
    from main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=API_PORT, log_level="warning", lifespan="on",
                            loop="asyncio")  # asyncio loop so the fixture DNS mapping applies (uvloop resolves on its own)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", API_PORT), timeout=0.2):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("API did not start")


async def ensure_user(email: str, password: str) -> None:
    import secrets
    from passlib.context import CryptContext
    from sqlalchemy import select

    import models  # noqa: F401 — registers every table
    from config.database import AsyncSessionLocal, init_db
    from models.user import User

    await init_db()
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is None:
            db.add(User(name="E2E Admin", email=email,
                        hashed_password=CryptContext(schemes=["bcrypt"]).hash(password),
                        api_key=secrets.token_hex(16), role="Admin", is_active=True, auditpulse_access=True))
            await db.commit()


def api(client, method, path, **kw):
    r = client.request(method, f"http://127.0.0.1:{API_PORT}/api/v1{path}", **kw)
    return r


def run_audit(client, url: str, modules) -> int:
    r = api(client, "POST", "/audits/", json={"url": url, "modules": modules, "depth": "homepage"})
    assert r.status_code == 202, r.text
    audit_id = r.json()["id"]
    for _ in range(240):
        p = api(client, "GET", f"/audits/{audit_id}/progress").json()
        if p["status"] in ("completed", "failed"):
            break
        time.sleep(1)
    check(f"audit {audit_id} ({url}) completed", p["status"] == "completed", json.dumps(p))
    return audit_id


def frontend_screenshots(token_payload: dict, audits: dict) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-proxy-server"])
        ctx = browser.new_context(viewport={"width": 1366, "height": 1000})
        ctx.add_init_script(
            "window.sessionStorage.setItem('auditpulse:session', %s);"
            "window.localStorage.setItem('auditpulse:session', %s);"
            % (json.dumps(json.dumps(token_payload)), json.dumps(json.dumps(token_payload))))
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        for name, audit_id in audits.items():
            page.goto(f"http://127.0.0.1:{WEB_PORT}/report.html?id={audit_id}#consent")
            try:
                page.wait_for_selector("#consentEvidenceDashboard .cev-tile", timeout=20_000)
                ok = True
            except Exception:  # noqa: BLE001
                ok = False
            check(f"report.html renders consent dashboard for {name}", ok, "; ".join(errors[-3:]))
            page.evaluate("document.querySelector('#consent') && (document.querySelector('#consent').open = true)")
            page.evaluate("document.querySelectorAll('#consent details').forEach(d => d.open = true)")
            page.wait_for_timeout(800)
            el = page.query_selector("#consent")
            if el:
                el.screenshot(path=str(OUT / f"report_consent_{name}.png"))
            text = page.inner_text("#consent") if el else ""
            RESULTS["audits"][name]["report_page_text_excerpt"] = text[:1500]
            if name == "global_unknown":
                check("report page shows 'Not assessed' for unknown region", "Not assessed" in text)
                check("report page shows GDPR section hidden for unknown region",
                      page.eval_on_selector("#consentGdprSection", "e => e.style.display") == "none")
                check("report page lists 'Accept only strictly necessary cookies' → reject_non_essential",
                      "Accept only strictly necessary cookies" in text and "reject_non_essential" in text)
            if name == "eu_onetrust":
                check("report page shows GTM as observation", "Observation" in text and "Tag manager" in text)
                check("report page shows GDPR section for EU", page.eval_on_selector(
                    "#consentGdprSection", "e => e.style.display") != "none")
        page.goto(f"http://127.0.0.1:{WEB_PORT}/dashboard.html")
        page.wait_for_timeout(6000)
        page.screenshot(path=str(OUT / "dashboard.png"), full_page=True)
        RESULTS["frontend_js_errors"] = errors
        check("no JavaScript errors on report/dashboard pages", not errors, "; ".join(errors[:3]))
        browser.close()


def main() -> int:
    import httpx

    print(f"Output: {OUT}\nAPI :{API_PORT}  web :{WEB_PORT}  fixtures :{fx.PORT}\nDB  {os.environ.get('DATABASE_URL', '(settings default)')}")
    start_fixture_server()
    start_frontend_server()
    email, password = "e2e-admin@example.com", "E2e-pass-1234"
    asyncio.run(ensure_user(email, password))
    start_api()

    client = httpx.Client(timeout=120, trust_env=False)
    login = api(client, "POST", "/auth/login", json={"email": email, "password": password})
    check("login", login.status_code == 200, login.text[:200])
    token = login.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"

    sites = {
        "eu_onetrust": ("www.example-shop.de", ["consent", "analytics"]),
        "global_unknown": ("www.globalco.com", ["consent"]),
        "india_iframe": ("news.example.in", ["consent"]),
        "continue_only_fr": ("boutique.example.fr", ["consent"]),
        "no_banner": ("plain.example.com", ["consent"]),
    }
    audits = {}
    for name, (host, modules) in sites.items():
        print(f"\n== {name}: {host} {modules}")
        audit_id = run_audit(client, fx.site_url(host), modules)
        audits[name] = audit_id
        consent = api(client, "GET", f"/audits/{audit_id}/consent").json()
        view = consent.get("report_view") or {}
        RESULTS["audits"][name] = {
            "audit_id": audit_id,
            "consent_score": consent.get("consent_score"),
            "region": [consent.get("detected_region"), consent.get("region_confidence")],
            "applicable_frameworks": consent.get("applicable_frameworks"),
            "applicability_status": consent.get("applicability_status"),
            "region_evidence": consent.get("region_evidence"),
            "consent_controls": consent.get("consent_controls"),
            "gdpr_checks": consent.get("gdpr_checks"),
            "ccpa_checks": consent.get("ccpa_checks"),
            "tiles": [(t["label"], t["value"], t["state"]) for t in view.get("tiles", [])],
            "screenshots": {s["key"]: s["captured"] for s in view.get("screenshots", [])},
            "pipeline": [(p["step"], p["name"], p["status"]) for p in view.get("pipeline", [])],
            "scan_id": (view.get("status") or {}).get("scan_id"),
        }
        check(f"{name}: consent row has report_view", bool(view) and not view.get("legacy"))
        check(f"{name}: 11-step fresh pipeline recorded", len(view.get("pipeline", [])) == 11)

        exp = api(client, "GET", f"/reports/{audit_id}/export.json")
        check(f"{name}: export.json 200 with consent_view", exp.status_code == 200 and bool(exp.json().get("consent_view")),
              str(exp.status_code))
        pdf = api(client, "GET", f"/reports/{audit_id}/export", params={"format": "pdf"})
        is_pdf = pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        check(f"{name}: PDF export", is_pdf, f"{pdf.status_code} {pdf.headers.get('content-type')}")
        if is_pdf:
            (OUT / f"report_{name}.pdf").write_bytes(pdf.content)
        z = api(client, "GET", f"/reports/{audit_id}/evidence.zip")
        names = zipfile.ZipFile(io.BytesIO(z.content)).namelist() if z.status_code == 200 else []
        check(f"{name}: evidence.zip has consent/ files",
              {"consent/summary.json", "consent/banner-controls.json", "consent/network-classified.json",
               "consent/region-applicability.json", "consent/scan-pipeline.json"} <= set(names), str(names))
        RESULTS["audits"][name]["evidence_zip"] = names
        if z.status_code == 200:
            (OUT / f"evidence_{name}.zip").write_bytes(z.content)

    a = RESULTS["audits"]
    # ---- behaviour assertions -------------------------------------------------
    eu = a["eu_onetrust"]
    check("EU: region EU + GDPR only", eu["region"][0] == "EU" and eu["applicable_frameworks"] == ["gdpr"])
    check("EU: CCPA not assessed (empty)", eu["ccpa_checks"] == {})
    check("EU: controls from rendered banner",
          [(c["label"], c["action"]) for c in eu["consent_controls"] if c["layer"] == 1]
          == [("Accept All Cookies", "accept_all"), ("Reject All", "reject_all"), ("Cookie Settings", "manage_preferences")])
    check("EU: tracking before consent = none (GTM only)", ("Tracking before consent", "None observed", "pass") in
          [tuple(t) for t in eu["tiles"]])
    check("EU: reject blocks tracking / accept enables", any(t[0] == "Reject works" and t[2] == "pass" for t in eu["tiles"])
          and any(t[0] == "Accept works" and t[2] == "pass" for t in eu["tiles"]))
    check("EU: 4 screenshots captured", all(eu["screenshots"].values()), str(eu["screenshots"]))

    g = a["global_unknown"]
    check("Unknown: region UNKNOWN/low/not_determined",
          g["region"] == ["UNKNOWN", "low"] and g["applicability_status"] == "not_determined")
    check("Unknown: no GDPR/CCPA verdicts", g["gdpr_checks"] == {} and g["ccpa_checks"] == {})
    check("Unknown: tracking before consent detected", any(t[0] == "Tracking before consent" and t[2] == "fail" for t in g["tiles"]))
    check("Unknown: reject does not stop tracking", any(t[0] == "Reject works" and t[2] == "fail" for t in g["tiles"]))

    i = a["india_iframe"]
    check("India: DPDP only, high confidence", i["applicable_frameworks"] == ["dpdp"] and i["region"] == ["IN", "high"])
    check("India: iframe CMP controls", ("Continue without accepting", "reject_non_essential") in
          [(c["label"], c["action"]) for c in i["consent_controls"]])

    f = a["continue_only_fr"]
    check("Continue-only: recorded as reject_non_essential, no accept invented",
          [(c["label"], c["action"]) for c in f["consent_controls"]] == [("Continue without accepting", "reject_non_essential")]
          and any(t[0] == "Accept works" and t[2] == "not_tested" for t in f["tiles"]))

    n = a["no_banner"]
    check("No banner: nothing classified as consent control", n["consent_controls"] == [])
    check("No banner: banner tile = Not detected", any(t[0] == "Consent banner" and t[1] == "Not detected" for t in n["tiles"]))

    # ---- fresh rescan ---------------------------------------------------------
    print("\n== re-scan eu_onetrust (fresh scan check)")
    rescan_id = run_audit(client, fx.site_url("www.example-shop.de"), ["consent"])
    c2 = api(client, "GET", f"/audits/{rescan_id}/consent").json()
    v2 = c2["report_view"]
    check("Re-scan: new scan id", v2["status"]["scan_id"] != eu["scan_id"],
          f"{v2['status']['scan_id']} vs {eu['scan_id']}")
    check("Re-scan: new screenshot files", set(filter(None, [s.get("url") for s in v2["screenshots"]])).isdisjoint(
        set(filter(None, [s.get("url") for s in (api(client, 'GET', f"/audits/{eu['audit_id']}/consent").json()
                                                  ['report_view']['screenshots'])]))))
    rr = c2.get("runtime_result") or {}
    check("Re-scan: before-consent cookie jar starts clean (no _ga from the first scan's Accept)",
          not any("_ga" in s for s in (rr.get("before_consent") or {}).get("cookie_buckets", {}).get("consent_required", [])))
    RESULTS["rescan_audit_id"] = rescan_id

    # ---- frontend ---------------------------------------------------------------
    print("\n== frontend (report.html / dashboard.html)")
    frontend_screenshots({"token": token, "user": login.json()["user"]}, audits)

    (OUT / "e2e_summary.json").write_text(json.dumps(RESULTS, indent=2, default=str))
    total = len(RESULTS["checks"])
    print(f"\n{total - len(FAILED)}/{total} checks passed. Summary: {OUT / 'e2e_summary.json'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
