"""
ai/provider.py

Single low-level entry point for talking to the configured AI provider
(config.settings.AI_PROVIDER / ANTHROPIC_API_KEY). Every other module in
this package (executive_summary.py, recommendations.py, business_impact.py,
action_plan.py, chatbot.py) calls through `call_ai` / `call_ai_json` rather
than touching httpx or the Anthropic API directly, so there's exactly one
place that knows the request shape, the timeout, and how a response gets
turned back into text.

Deliberately NOT fail-safe: `call_ai` / `call_ai_json` raise `AIProviderError`
on anything that goes wrong (unconfigured provider, network failure, bad
response shape, invalid JSON). Callers — not this module — decide what a
failure means for them (most fall back to a deterministic heuristic, see
each module's `_heuristic_*` function), the same division of responsibility
services.ai_service used before this package existed.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

import httpx

from config.logging import logger
from config.settings import settings

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Every module in this package uses the same model unless a caller has a
# specific reason not to (none currently do) — keep it in one place.
AI_MODEL = "claude-sonnet-4-6"

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_TOKENS = 500


class AIProviderError(Exception):
    """Raised for any failure calling the AI provider — missing config, network, or parse errors."""


def is_configured() -> bool:
    """True when a real provider call can be attempted at all."""
    return settings.AI_PROVIDER == "anthropic" and bool(settings.ANTHROPIC_API_KEY)


async def call_ai(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """
    Sends a single user-turn message to the configured provider and returns
    the concatenated text of the response. Raises AIProviderError if no
    provider is configured, the request fails, or the response has no text
    content — never returns an empty/placeholder string silently.
    """
    if not is_configured():
        raise AIProviderError(
            f"AI provider not configured (AI_PROVIDER={settings.AI_PROVIDER!r}, "
            f"ANTHROPIC_API_KEY {'set' if settings.ANTHROPIC_API_KEY else 'missing'})"
        )

    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload: dict = {
        "model": AI_MODEL,
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


async def call_ai_json(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """
    Like `call_ai`, but parses the response as JSON. The prompt should
    instruct the model to return ONLY JSON (no prose, no markdown fences) —
    this still strips ``` fences defensively since models don't always obey
    that instruction perfectly. Raises AIProviderError if the result isn't
    valid JSON.
    """
    text = await call_ai(prompt, system=system, max_tokens=max_tokens, timeout=timeout)
    cleaned = _strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning(f"ai.provider: could not parse JSON from AI response: {exc}")
        raise AIProviderError(f"Anthropic response was not valid JSON: {exc}") from exc


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
