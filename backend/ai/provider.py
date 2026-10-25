"""
The one place that calls the AI provider (AI_PROVIDER = "groq" or "anthropic").

call_ai / call_ai_json raise AIProviderError on any failure; each caller
decides its own fallback.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

import httpx

from config.logging import logger
from config.settings import settings

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Default model per provider. Set AI_MODEL to override (e.g. when a model is retired).
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "groq": "openai/gpt-oss-120b",
}
# Kept for older imports.
AI_MODEL = DEFAULT_MODELS["anthropic"]

# gpt-oss models spend tokens thinking first; extra room so the answer isn't cut off.
GROQ_REASONING_HEADROOM = 1500

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_TOKENS = 500


class AIProviderError(Exception):
    """Any AI call failure: missing key, network or bad response."""


def _provider() -> str:
    return (settings.AI_PROVIDER or "").strip().lower()


def _model() -> str:
    override = (getattr(settings, "AI_MODEL", "") or "").strip()
    return override or DEFAULT_MODELS.get(_provider(), "")


def is_configured() -> bool:
    """True when a real provider call can be attempted at all."""
    provider = _provider()
    if provider == "anthropic":
        return bool(settings.ANTHROPIC_API_KEY)
    if provider == "groq":
        return bool(getattr(settings, "GROQ_API_KEY", ""))
    return False


async def call_ai(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Sends one prompt and returns the reply text. Raises AIProviderError on any failure."""
    if not is_configured():
        raise AIProviderError(
            f"AI provider not configured (AI_PROVIDER={settings.AI_PROVIDER!r}; set ANTHROPIC_API_KEY "
            f"or AI_PROVIDER=groq with GROQ_API_KEY)"
        )
    if _provider() == "groq":
        return await _call_groq(prompt, system=system, max_tokens=max_tokens, timeout=timeout)

    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload: dict = {
        "model": _model(),
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise AIProviderError(f"Anthropic request failed: {exc}") from exc

    text = _extract_text(data)
    if not text:
        raise AIProviderError("Anthropic response contained no text content")
    return text


async def _call_groq(prompt: str, *, system: Optional[str], max_tokens: int, timeout: float) -> str:
    """Groq chat API (OpenAI-compatible, free tier)."""
    model = _model()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload: dict = {"model": model, "messages": messages, "temperature": 0.3}
    if model.startswith("openai/gpt-oss"):
        payload["max_completion_tokens"] = max_tokens + GROQ_REASONING_HEADROOM
        payload["reasoning_effort"] = "low"
        payload["include_reasoning"] = False
    else:
        payload["max_completion_tokens"] = max_tokens
    headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(GROQ_API_URL, headers=headers, json=payload)
            if response.status_code == 429:
                raise AIProviderError("Groq free-tier rate limit reached; using the built-in summary instead")
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        detail = ""
        if isinstance(exc, httpx.HTTPStatusError):
            detail = f" — {exc.response.text[:200]}"
        raise AIProviderError(f"Groq request failed: {exc}{detail}") from exc

    try:
        text = (data["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise AIProviderError(f"Unexpected Groq response shape: {exc}") from exc
    if not text:
        raise AIProviderError("Groq response contained no text content")
    return text


async def call_ai_json(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Like call_ai, but parses the reply as JSON (code fences are stripped)."""
    text = await call_ai(prompt, system=system, max_tokens=max_tokens, timeout=timeout)
    cleaned = _strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning(f"ai.provider: could not parse JSON from AI response: {exc}")
        raise AIProviderError(f"AI response was not valid JSON: {exc}") from exc


def _extract_text(data: dict) -> str:
    blocks: List[dict] = data.get("content", []) or []
    return "".join(block.get("text", "") for block in blocks if block.get("type") == "text").strip()


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        if stripped.endswith("```"):
            stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()
