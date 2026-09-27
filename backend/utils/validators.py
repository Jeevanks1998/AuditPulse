"""
utils/validators.py

Standalone validation helpers for places that need a plain bool/reason
check rather than a full Pydantic model — inside services, background
jobs, or CLI scripts (database/seed.py, scheduler/) where request
bodies (schemas/*.py, already validated by FastAPI on the way in)
aren't in play. `is_valid_email` deliberately reuses the same
`email-validator` package pydantic's `EmailStr` (schemas/user.py) is
built on, so "valid email" means the same thing in both places.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63}(?<!-))*\.[A-Za-z]{2,63}$"
)
_API_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def is_valid_email(email: str) -> bool:
    """True if `email` is a syntactically valid, deliverable-looking
    address. Uses the same `email-validator` package as
    `schemas.user.UserRegister.email: EmailStr`, so results agree with
    what the registration endpoint will ultimately accept."""
    if not email:
        return False
    try:
        from email_validator import EmailNotValidError, validate_email

        validate_email(email, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def is_valid_password(password: str, min_length: int = 6) -> Tuple[bool, Optional[str]]:
    """
    Matches `schemas.user.UserRegister.password`'s `min_length=6` floor
    as the hard requirement, then flags (without failing) the common
    weak-password patterns — callers that want stricter enforcement
    than the schema check `ok` AND look at `reason`; callers that just
    want the schema's own floor only need `ok`.

    Returns (is_valid, reason_if_invalid).
    """
    if not password or len(password) < min_length:
        return False, f"Password must be at least {min_length} characters."
    if password.isdigit():
        return False, "Password can't be only numbers."
    if password.lower() in {"password", "123456", "letmein", "qwerty"}:
        return False, "Password is too common."
    return True, None


def is_valid_hostname(value: str) -> bool:
    """True for well-formed DNS hostnames (`example.com`, `sub.example.co.uk`),
    not raw IPs or URLs — use `utils.urls.is_valid_url` for full URLs."""
    if not value or len(value) > 253:
        return False
    return bool(_HOSTNAME_RE.match(value))


def is_valid_api_key(value: str) -> bool:
    """Shape-check for an AuditPulse API key (models.user.User.api_key,
    generated with `secrets.token_hex(24)` -> 48 hex chars). Doesn't
    check it exists in the DB — that's `middleware.auth`'s job."""
    return bool(value) and bool(_API_KEY_RE.match(value))


def is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def is_within_length(value: str, min_length: int = 0, max_length: int = 10_000) -> bool:
    return isinstance(value, str) and min_length <= len(value) <= max_length


def validate_pagination(page: int, page_size: int) -> Tuple[int, int]:
    """
    Clamps user-supplied pagination params to sane bounds instead of
    raising, mirroring `config.constants.DEFAULT_PAGE_SIZE`/`MAX_PAGE_SIZE`
    (api/history.py and any future paginated list endpoint can call this
    on raw query params before building the SQL `LIMIT`/`OFFSET`).
    """
    safe_page = max(1, page)
    if page_size <= 0:
        safe_size = DEFAULT_PAGE_SIZE
    else:
        safe_size = min(page_size, MAX_PAGE_SIZE)
    return safe_page, safe_size


__all__ = [
    "is_valid_email",
    "is_valid_password",
    "is_valid_hostname",
    "is_valid_api_key",
    "is_non_empty_string",
    "is_within_length",
    "validate_pagination",
]
