"""
Reads raw Set-Cookie header strings into Cookie objects. A small custom
parser, because http.cookies.SimpleCookie drops some real-world cookies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse

_KNOWN_ATTRS = {"expires", "max-age", "domain", "path", "secure", "httponly", "samesite"}


@dataclass
class Cookie:
    name: str
    value: str
    domain: Optional[str] = None
    path: Optional[str] = None
    secure: bool = False
    http_only: bool = False
    same_site: Optional[str] = None  # "Strict" | "Lax" | "None" | None (unset)
    max_age_seconds: Optional[float] = None  # from Max-Age, else Expires; None = session cookie
    source_url: Optional[str] = None  # page that set it
    raw: str = field(default="", repr=False)


def parse_set_cookie_headers(headers: List[str], source_url: Optional[str] = None) -> List[Cookie]:
    """Parses every Set-Cookie header of one response."""
    cookies: List[Cookie] = []
    for raw in headers or []:
        parsed = _parse_one(raw, source_url)
        if parsed is not None:
            cookies.append(parsed)
    return cookies


def merge_cookie_lists(*lists: List[Cookie]) -> List[Cookie]:
    """Removes duplicates across pages by (name, domain, path), keeping the first."""
    seen = set()
    merged: List[Cookie] = []
    for cookie_list in lists:
        for cookie in cookie_list:
            key = (cookie.name, cookie.domain, cookie.path)
            if key in seen:
                continue
            seen.add(key)
            merged.append(cookie)
    return merged


def _parse_one(raw: str, source_url: Optional[str]) -> Optional[Cookie]:
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    if not parts:
        return None

    name_value = parts[0]
    if "=" not in name_value:
        return None
    name, _, value = name_value.partition("=")
    name = name.strip()
    if not name:
        return None

    cookie = Cookie(name=name, value=value.strip(), source_url=source_url, raw=raw)
    max_age_seconds: Optional[float] = None
    expires_seconds: Optional[float] = None

    for attr in parts[1:]:
        if "=" in attr:
            attr_name, _, attr_value = attr.partition("=")
        else:
            attr_name, attr_value = attr, ""
        attr_key = attr_name.strip().lower()
        attr_value = attr_value.strip()

        if attr_key == "domain":
            cookie.domain = attr_value.lstrip(".") or None
        elif attr_key == "path":
            cookie.path = attr_value or "/"
        elif attr_key == "secure":
            cookie.secure = True
        elif attr_key == "httponly":
            cookie.http_only = True
        elif attr_key == "samesite":
            cookie.same_site = attr_value.title() or None
        elif attr_key == "max-age":
            try:
                max_age_seconds = float(attr_value)
            except ValueError:
                pass
        elif attr_key == "expires":
            expires_seconds = _expires_to_max_age(attr_value)

    cookie.max_age_seconds = max_age_seconds if max_age_seconds is not None else expires_seconds

    if not cookie.domain and source_url:
        cookie.domain = urlparse(source_url).hostname

    return cookie


def _expires_to_max_age(expires_value: str) -> Optional[float]:
    """Expires date -> seconds from now."""
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime

    try:
        expires_dt = parsedate_to_datetime(expires_value)
    except (TypeError, ValueError):
        return None
    if expires_dt is None:
        return None
    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=timezone.utc)

    delta = (expires_dt - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, delta)


def is_third_party(cookie: Cookie, first_party_hostname: Optional[str]) -> bool:
    """Third-party when the cookie's domain isn't the site's own domain (or a parent of it)."""
    if not cookie.domain or not first_party_hostname:
        return False
    cookie_domain = cookie.domain.lower().lstrip(".")
    site_host = first_party_hostname.lower()
    return not (site_host == cookie_domain or site_host.endswith("." + cookie_domain))
