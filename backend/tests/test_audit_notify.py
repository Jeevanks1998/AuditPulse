"""'Audit finished' email: message text and the never-raise guard."""

import asyncio
from types import SimpleNamespace

from services import audit_notify


def _audit(**kw):
    base = dict(id=42, url="https://www.example.com/", status="completed", overall_score=82,
                breakdown={"consent": 90, "analytics": 70}, error_message=None,
                findings=[{"severity": "critical"}, {"severity": "warning"}, {"severity": "warning"}])
    base.update(kw)
    return SimpleNamespace(**base)


def test_completed_message():
    subject, body = audit_notify.build_message(_audit(), "Jeevan K S", "https://app.example")
    assert subject == "Audit complete: www.example.com scored 82/100"
    assert body.startswith("Hi Jeevan,")
    assert "Overall score: 82/100 (Healthy)" in body
    assert "Issues: 1 critical, 2 warnings" in body
    assert "https://app.example/report.html?id=42" in body


def test_failed_message():
    subject, body = audit_notify.build_message(
        _audit(status="failed", error_message="Site blocked the audit"), "", "")
    assert subject == "Audit failed: www.example.com"
    assert "Hi there," in body and "Site blocked the audit" in body


def test_not_scored():
    _, body = audit_notify.build_message(_audit(overall_score=None, breakdown={}), "A", "")
    assert "Overall score: not scored\n" in body
    assert "report.html" not in body


def test_frontend_url_falls_back_to_https_origin(monkeypatch):
    monkeypatch.setattr(audit_notify.settings, "FRONTEND_URL", "")
    monkeypatch.setattr(audit_notify.settings, "CORS_ORIGINS_RAW", "http://localhost:3000,https://ap.vercel.app/")
    assert audit_notify.frontend_url() == "https://ap.vercel.app"


def test_email_off_sends_nothing(monkeypatch):
    monkeypatch.setattr(audit_notify.settings, "SMTP_HOST", "")
    assert asyncio.run(audit_notify.notify_audit_finished(1)) is None
