"""
ux/readability.py

Readability of the page's actual visible copy: a Flesch Reading Ease
score computed from crawler.parser.ParsedPage.text_content (already
extracted, script/style-stripped), plus a structural check for long
unbroken paragraphs that make even easy-to-read text feel dense on a
page.

The Flesch score here is a heuristic syllable-count approximation
(vowel-group counting), not a linguistically precise syllabifier —
accurate enough to flag "this reads like a legal document" vs "this
reads like a blog post" without pulling in an NLP dependency, which is
the same tradeoff performance/metrics.py's fallback measurement makes
for load timing versus a real browser.
"""

from __future__ import annotations

import re
from typing import List, Optional

from crawler.parser import ParsedPage

MODULE = "ux"
CATEGORY = "readability"

MIN_WORDS_TO_JUDGE = 100  # too little copy for a Flesch score to mean anything

# Flesch Reading Ease bands (0-100, higher = easier).
FLESCH_DIFFICULT = 30   # "very difficult" and below
FLESCH_FAIRLY_DIFFICULT = 50

LONG_PARAGRAPH_WORDS = 150  # a single <p> this long reads as a wall of text

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+(?:\s|$)")
_WORD_RE = re.compile(r"[A-Za-z']+")
_VOWEL_GROUP_RE = re.compile(r"[aeiouyAEIOUY]+")


def check_readability(page: ParsedPage) -> List[dict]:
    """Findings for hard-to-read body copy and unbroken long paragraphs."""
    findings: List[dict] = []
    findings += _check_flesch_score(page)
    findings += _check_long_paragraphs(page)
    return findings


def _check_flesch_score(page: ParsedPage) -> List[dict]:
    if page.word_count < MIN_WORDS_TO_JUDGE:
        return []

    score = _flesch_reading_ease(page.text_content)
    if score is None or score >= FLESCH_FAIRLY_DIFFICULT:
        return []

    severity = "warning" if score < FLESCH_DIFFICULT else "info"
    band = "very difficult to read" if score < FLESCH_DIFFICULT else "fairly difficult to read"
    return [_finding(
        severity,
        "Body copy scores as hard to read",
        f"{page.url}'s visible text scores {score:.0f}/100 on the Flesch Reading Ease scale "
        f"({band}) — driven by long sentences and/or long, multi-syllable words. General "
        "audiences typically read most comfortably in the 60-70 range (roughly an 8th-grade "
        "reading level).",
        recommendation="Shorten sentences, prefer plain words over jargon where the "
                        "audience doesn't require it, and break up dense paragraphs — "
                        "aim for a Flesch score in the 60s for general-audience content.",
    )]


def _check_long_paragraphs(page: ParsedPage) -> List[dict]:
    long_paragraphs = 0
    for p in page.soup.find_all("p"):
        text = p.get_text(strip=True)
        word_count = len(text.split())
        if word_count >= LONG_PARAGRAPH_WORDS:
            long_paragraphs += 1

    if not long_paragraphs:
        return []

    return [_finding(
        "info",
        "Long unbroken paragraphs",
        f"{page.url} has {long_paragraphs} paragraph(s) of {LONG_PARAGRAPH_WORDS}+ words "
        "with no sub-heading, list, or line break inside them. Even well-written copy reads "
        "as a dense wall of text at that length, which most visitors skim past rather than "
        "read.",
        recommendation="Break long paragraphs into shorter ones, and introduce "
                        "sub-headings, bullet lists, or pull quotes to give the eye places "
                        "to rest.",
    )]


def _flesch_reading_ease(text: str) -> Optional[float]:
    words = _WORD_RE.findall(text)
    if len(words) < MIN_WORDS_TO_JUDGE:
        return None

    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    sentence_count = max(1, len(sentences))
    syllable_count = sum(_estimate_syllables(w) for w in words)

    words_per_sentence = len(words) / sentence_count
    syllables_per_word = syllable_count / len(words)

    score = 206.835 - (1.015 * words_per_sentence) - (84.6 * syllables_per_word)
    return max(0.0, min(100.0, score))


def _estimate_syllables(word: str) -> int:
    groups = _VOWEL_GROUP_RE.findall(word)
    count = len(groups)
    if word.lower().endswith("e") and count > 1:
        count -= 1  # silent trailing e
    return max(1, count)


def _finding(severity: str, title: str, description: str, recommendation: Optional[str] = None) -> dict:
    return {
        "module": MODULE,
        "category": CATEGORY,
        "severity": severity,
        "title": title,
        "description": description,
        "recommendation": recommendation,
    }
