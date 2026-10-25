"""
Simple validation helpers for code outside request handling (services, jobs, scripts).
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
    """True for a valid email address (same rules as the API's EmailStr)."""
    if not email:
        return False
    try:
        from email_validator import EmailNotValidError, validate_email

        validate_email(email, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def is_valid_password(password: str, min_length: int = 6) -> Tuple[bool, Optional[str]]:
    """Checks the minimum length and flags common weak passwords. Returns (ok, reason)."""
    if not password or len(password) < min_length:
        return False, f"Password must be at least {min_length} characters."
    if password.isdigit():
        return False, "Password can't be only numbers."
    if password.lower() in {"password", "123456", "letmein", "qwerty"}:
        return False, "Password is too common."
    return True, None


def is_valid_hostname(value: str) -> bool:
    """True for a host name like example.com (not an IP or URL)."""
    if not value or len(value) > 253:
        return False
    return bool(_HOSTNAME_RE.match(value))


def is_valid_api_key(value: str) -> bool:
    """Checks an API key's format (not whether it exists)."""
    return bool(value) and bool(_API_KEY_RE.match(value))


def is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def is_within_length(value: str, min_length: int = 0, max_length: int = 10_000) -> bool:
    return isinstance(value, str) and min_length <= len(value) <= max_length


def validate_pagination(page: int, page_size: int) -> Tuple[int, int]:
    """Keeps page and page size within allowed bounds."""
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
