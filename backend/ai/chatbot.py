"""
Answers questions about one completed audit, using only that audit's data.

If the AI is unavailable it says so plainly; it never makes up an answer.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from config.logging import logger
from ai.provider import AIProviderError, call_ai

MAX_HISTORY_TURNS = 6  # earlier question/answer pairs sent as context
UNAVAILABLE_MESSAGE = (
    "I can't reach the AI assistant right now (no provider configured, or the request failed). "
    "You can still review the full findings list and score breakdown in the report above."
)


async def ask_about_audit(
    question: str,
    url: str,
    overall: int,
    breakdown: Dict[str, int],
    findings: Optional[List[dict]] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Answers `question` about one audit. `history` holds earlier {"question", "answer"} turns, oldest first."""
    question = (question or "").strip()
    if not question:
        return "Ask me anything about this audit — for example, \"what should I fix first?\""

    try:
        return await _answer_from_ai(question, url, overall, breakdown, findings or [], history or [])
    except AIProviderError as exc:
        logger.warning(f"ai.chatbot: could not answer question, provider unavailable: {exc}")
        return UNAVAILABLE_MESSAGE


async def _answer_from_ai(
    question: str,
    url: str,
    overall: int,
    breakdown: Dict[str, int],
    findings: List[dict],
    history: List[Dict[str, str]],
) -> str:
    system = (
        "You are the AI assistant embedded in a website audit report. Answer the user's question "
        "using ONLY the audit data provided below — never invent scores, findings, or facts about "
        "the site that aren't given to you. If the data doesn't cover what's being asked, say so "
        "plainly rather than guessing. Keep answers concise (a few sentences) and practical."
    )

    condensed_findings = [
        {"module": f.get("module"), "severity": f.get("severity"), "title": f.get("title")}
        for f in findings[:25]
    ]
    context = (
        f"Audited URL: {url}\nOverall score: {overall}/100\nModule breakdown: {breakdown}\n"
        f"Findings: {condensed_findings}"
    )

    transcript = "\n".join(
        f"Q: {turn.get('question', '')}\nA: {turn.get('answer', '')}" for turn in history[-MAX_HISTORY_TURNS:]
    )

    prompt = context
    if transcript:
        prompt += f"\n\nPrior conversation:\n{transcript}"
    prompt += f"\n\nQuestion: {question}"

    return (await call_ai(prompt, system=system, max_tokens=400)).strip()
