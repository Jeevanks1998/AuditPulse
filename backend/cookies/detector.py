"""
cookies/detector.py

Parses raw `Set-Cookie` response header strings into structured
`Cookie` objects. Takes strings rather than an httpx.Response so the
caller decides where the headers came from — crawler.crawler's
httpx.AsyncClient responses (crawler/crawler.py's `_fetch_one` doesn't
currently expose them, so a caller wiring this in reads
`response.headers.get_list("set-cookie")` before that page's ParsedPage
goes out of scope), a Playwright page's `context.cookies()` normalized
to the same header string shape, or a fixture in a test.

Deliberately doesn't use `http.cookies.SimpleCookie` — it silently
drops cookies with certain characters/casing quirks real sites still
send, and it can't represent more than one Set-Cookie line with the
same name from different paths. A small hand-rolled parser here keeps
every cookie the server actually sent.
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
    max_age_seconds: Optional[float] = None  # resolved from Max-Age, else Expires; None = session
    source_url: Optional[str] = None  # page that set it, for cross-referencing with consent timing
    raw: str = field(default="", repr=False)


def parse_set_cookie_headers(headers: List[str], source_url: Optional[str] = None) -> List[Cookie]:
    """Parses every `Set-Cookie` header value seen for one response into Cookie objects."""
    cookies: List[Cookie] = []
    for raw in headers or []:
        parsed = _parse_one(raw, source_url)
        if parsed is not None:
            cookies.append(parsed)
    return cookies


def merge_cookie_lists(*lists: List[Cookie]) -> List[Cookie]:
    """
    De-dupes across pages/requests by (name, domain, path) — same
    cookie re-set on every page shouldn't be counted N times in an
    N-page crawl. Keeps the first occurrence (earliest set).
    """
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
    """Best-effort `Expires=<HTTP-date>` -> seconds-from-now, matching Max-Age's shape."""
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
    """A cookie is third-party if its domain doesn't match (or isn't a parent of) the site's own hostname."""
    if not cookie.domain or not first_party_hostname:
        return False
    cookie_domain = cookie.domain.lower().lstrip(".")
    site_host = first_party_hostname.lower()
    return not (site_host == cookie_domain or site_host.endswith("." + cookie_domain))
