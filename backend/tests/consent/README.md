# Consent module tests (Phases 1–4)

All tests run against local fixture sites in `fixtures/` — no real website
or internet access is needed. Chromium is told to resolve every hostname
(www.example-shop.de, www.googletagmanager.com, cdn.privacy-mgmt.com, …) to
the local fixture server, so the classification code sees realistic hosts.

| Fixture | What it exercises |
|---|---|
| `eu_onetrust.html` (`www.example-shop.de`) | client-rendered OneTrust-style banner, GTM before consent (observation), GA only after Accept, OptanonConsent / XSRF-TOKEN / session cookies, unrelated "Continue" + "Settings" outside the banner |
| `global_bad.html` (`www.globalco.com`) | unknown region, GA collect before consent, "Accept only strictly necessary cookies" that keeps tracking, Personalize that opens nothing |
| `iframe_cmp.html` + `cmp.html` (`news.example.in`) | India / DPDP, CMP inside an iframe, unrelated "Accept"/"OK" dialog on the page |
| `continue_only.html` (`boutique.example.fr`) | banner with only "Continue without accepting" |
| `ack_only.html` (`shop.example.co.uk`) | "OK" / "Got it" / "Close" only — none are accept/reject |
| `no_banner.html` (`plain.example.com`) | no banner; "Accept order" / "Continue" must not become consent controls |

## Run

From `backend/`:

```bash
pip install pytest pytest-asyncio
python -m pytest tests/consent -q          # unit + live-browser scans (~2 min)
```

Full application end to end (real API + real database + real pipeline +
report.html / dashboard.html in a browser, PDF / JSON / evidence ZIP exports):

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@127.0.0.1:5432/auditpulse \
  python -m tests.consent.run_full_app_e2e --out /tmp/ap-e2e
```

It prints PASS/FAIL per check, exits non-zero on any failure, and writes
`e2e_summary.json`, report-page screenshots, PDFs and evidence ZIPs to `--out`.
Playwright's Chromium must be installed (`playwright install chromium`).
