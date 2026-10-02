# Customer Journey tests

The fixture shop in `site/` (served locally as `www.journey-shop.com`) has a
consent banner, a nav, a CTA that is **not** tracked, a broken CTA, a
JavaScript-rendered CTA, a modal, an accordion, tabs, a video, phone/email
links, three downloads (one 404), three forms, a "Buy now" button and an
add-to-cart link (must never be executed), and fake GA4 / dataLayer tracking
that only fires after consent.

```bash
python -m pytest tests/journey -q          # unit + one live scan (~1.5 min)

# full application: API + database + pipeline + report/dashboard in a browser
DATABASE_URL=postgresql+asyncpg://user:pass@127.0.0.1:5432/auditpulse \
  python -m tests.journey.run_full_app_e2e --out /tmp/ap-journey-e2e
```
