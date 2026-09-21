"""
utils/formatter.py

Human-readable string formatting for API responses, log lines, and
generated reports (reports/, pdf/). `score_band` and
`format_relative_time` intentionally mirror `scoreBand` and
`formatRelativeTime` in assets/js/utils.js so a score or timestamp
reads the same whether it was formatted server-side (PDF/HTML export,
AI-generated report copy) or client-side (dashboard.html, history.html).
"""

from __future__ import annotations

from datetime import datetime, timezone

from config.constants import SCORE_BANDS


def score_band(score: int | float | None) -> str:
    """"good" | "mid" | "bad", using the same thresholds as
    `config.constants.SCORE_BANDS` (and assets/js/utils.js's `scoreBand`),
    so ring/chip coloring agrees between the API and the frontend."""
    if score is None:
        return "bad"
    value = float(score)
    if value >= SCORE_BANDS["good"]:
        return "good"
    if value >= SCORE_BANDS["mid"]:
        return "mid"
    return "bad"


def format_percentage(value: float, decimals: int = 0) -> str:
    return f"{value:.{decimals}f}%"


def format_bytes(num_bytes: float) -> str:
    """1536 -> "1.5 KB". Used for screenshot/report file sizes
    (utils.screenshots, utils.file_manager) and page-weight findings
    (performance/optimization.py)."""
    if num_bytes < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"  # pragma: no cover - astronomically unlikely


def format_duration(seconds: float) -> str:
    """0.4 -> "400ms", 75 -> "1m 15s", 5400 -> "1h 30m" — for crawl/audit
    step timings (utils.logger.log_duration, scheduler job summaries)."""
    if seconds < 0:
        seconds = 0
    if seconds < 1:
        return f"{round(seconds * 1000)}ms"
    total_seconds = int(round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_relative_time(when: datetime, *, now: datetime | None = None) -> str:
    """`2024-01-01T00:00:00Z` -> "3 days ago" / "just now" / "in 2 hours".
    Server-side counterpart to assets/js/utils.js's `formatRelativeTime`,
    for contexts that render a timestamp outside the browser (PDF export,
    AI-generated executive summaries, notification/email copy)."""
    reference = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    delta = reference - when
    seconds = delta.total_seconds()
    future = seconds < 0
    seconds = abs(seconds)

    if seconds < 45:
        return "just now"

    periods = (
        ("year", 60 * 60 * 24 * 365),
        ("month", 60 * 60 * 24 * 30),
        ("day", 60 * 60 * 24),
        ("hour", 60 * 60),
        ("minute", 60),
    )
    for label, span in periods:
        count = int(seconds // span)
        if count >= 1:
            unit = label if count == 1 else f"{label}s"
            return f"in {count} {unit}" if future else f"{count} {unit} ago"

    return "just now"


def truncate_text(text: str, max_length: int = 140, suffix: str = "\u2026") -> str:
    """Truncates on a word boundary where possible (report/notification
    previews, AI-summary snippets) rather than mid-word."""
    if not text or len(text) <= max_length:
        return text or ""
    cut = text[: max_length].rsplit(" ", 1)[0]
    return (cut or text[:max_length]).rstrip() + suffix


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """`pluralize(1, "issue")` -> "1 issue", `pluralize(3, "issue")` -> "3 issues"."""
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


__all__ = [
    "score_band",
    "format_percentage",
    "format_bytes",
    "format_duration",
    "format_relative_time",
    "truncate_text",
    "pluralize",
]
