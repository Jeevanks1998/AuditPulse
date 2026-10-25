"""
URL helpers: add scheme, validate, host name, main domain, same-site checks, tracking-parameter removal, normalising.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

_SCHEME_RE_PREFIX = ("http://", "https://")

# Tracking parameters removed before comparing URLs.
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"fbclid", "gclid", "gclsrc", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src"}


def ensure_scheme(url: str, default_scheme: str = "https") -> str:
    """`example.com` -> `https://example.com`; URLs with a scheme are unchanged."""
    value = (url or "").strip()
    if not value:
        return value
    if "//" in value.split("?", 1)[0][:12]:
        return value
    return f"{default_scheme}://{value}"


def is_valid_url(url: str) -> bool:
    """True for an absolute http(s) URL with a host name."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def hostname_of(url: str) -> str:
    """Lower-case host name without `www.` (URL or bare host)."""
    parsed = urlparse(url if "//" in url else f"//{url}")
    host = (parsed.hostname or url or "").lower()
    return host[4:] if host.startswith("www.") else host


def root_domain(url: str) -> str:
    """Rough main domain (`blog.example.co.uk` -> `example.co.uk`). Not for security decisions."""
    host = hostname_of(url)
    if not host:
        return ""
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    two_part_tlds = {"co.uk", "com.au", "co.jp", "com.br", "co.nz", "co.in"}
    if ".".join(labels[-2:]) in two_part_tlds and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def is_same_domain(url_a: str, url_b: str) -> bool:
    """True if both URLs share a main domain (is_internal_link is the stricter version)."""
    root_a, root_b = root_domain(url_a), root_domain(url_b)
    return bool(root_a) and root_a == root_b


def is_internal_link(link: str, base_url: str) -> bool:
    """True if `link` resolves to the same host name as `base_url`."""
    resolved = urljoin(base_url, link)
    return hostname_of(resolved) == hostname_of(base_url)


def join_url(base: str, path: str) -> str:
    """Resolves a relative link against its page (urljoin)."""
    return urljoin(base, path)


def strip_tracking_params(url: str) -> str:
    """Removes utm_* / fbclid / gclid etc., keeping other parameters in order."""
    parsed = urlparse(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
        and not any(key.lower().startswith(p) for p in _TRACKING_PARAM_PREFIXES)
    ]
    return urlunparse(parsed._replace(query=urlencode(kept)))


def normalize_url(url: str, *, strip_fragment: bool = True, strip_trailing_slash: bool = True) -> str:
    """URL for comparison only: lower-case scheme/host, no tracking parameters, no #fragment, no trailing slash."""
    parsed = urlparse(ensure_scheme(url))
    path = parsed.path or "/"
    if strip_trailing_slash and len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=path,
        fragment="" if strip_fragment else parsed.fragment,
    )
    return strip_tracking_params(urlunparse(normalized))


__all__ = [
    "ensure_scheme",
    "is_valid_url",
    "hostname_of",
    "root_domain",
    "is_same_domain",
    "is_internal_link",
    "join_url",
    "strip_tracking_params",
    "normalize_url",
]
