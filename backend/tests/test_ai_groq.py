"""Groq provider (free tier, OpenAI-compatible) in ai/provider.py — no network."""

import asyncio

import httpx
import pytest

from ai import provider
from config.settings import settings


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=httpx.Request("POST", provider.GROQ_API_URL), response=self)


def _patch(monkeypatch, status, body, seen):
    async def fake_post(self, url, headers=None, json=None):
        seen.update(url=url, headers=headers, json=json)
        return _Resp(status, body)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(settings, "AI_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(settings, "AI_MODEL", "")


def test_groq_text_and_request_shape(monkeypatch):
    seen = {}
    _patch(monkeypatch, 200, {"choices": [{"message": {"content": "Hello"}}]}, seen)
    assert provider.is_configured()
    assert asyncio.run(provider.call_ai("hi", system="be brief", max_tokens=300)) == "Hello"
    assert seen["url"] == provider.GROQ_API_URL
    assert seen["headers"]["Authorization"] == "Bearer gsk_test"
    body = seen["json"]
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["messages"][0] == {"role": "system", "content": "be brief"}
    assert body["max_completion_tokens"] == 300 + provider.GROQ_REASONING_HEADROOM
    assert body["include_reasoning"] is False


def test_groq_json(monkeypatch):
    _patch(monkeypatch, 200, {"choices": [{"message": {"content": '```json\n{"a": 1}\n```'}}]}, {})
    assert asyncio.run(provider.call_ai_json("x")) == {"a": 1}


def test_groq_rate_limit_and_empty_raise(monkeypatch):
    _patch(monkeypatch, 429, {}, {})
    with pytest.raises(provider.AIProviderError, match="rate limit"):
        asyncio.run(provider.call_ai("x"))
    _patch(monkeypatch, 200, {"choices": [{"message": {"content": ""}}]}, {})
    with pytest.raises(provider.AIProviderError):
        asyncio.run(provider.call_ai("x"))


def test_not_configured_without_key(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    assert not provider.is_configured()


def test_model_override(monkeypatch):
    seen = {}
    _patch(monkeypatch, 200, {"choices": [{"message": {"content": "ok"}}]}, seen)
    monkeypatch.setattr(settings, "AI_MODEL", "qwen/qwen3.8-27b")
    asyncio.run(provider.call_ai("x", max_tokens=100))
    assert seen["json"]["model"] == "qwen/qwen3.8-27b" and seen["json"]["max_completion_tokens"] == 100


def test_provider_label(monkeypatch):
    from ai import provider
    monkeypatch.setattr(provider.settings, "AI_PROVIDER", "groq")
    monkeypatch.setattr(provider.settings, "GROQ_API_KEY", "x" * 20)
    monkeypatch.setattr(provider.settings, "AI_MODEL", "")
    assert provider.provider_label() == "Groq · openai/gpt-oss-120b"
    monkeypatch.setattr(provider.settings, "GROQ_API_KEY", "")
    assert provider.provider_label().startswith("Not configured")
