"""
utils/urls.py

URL parsing/normalization helpers shared by the crawler, SEO/links
checks, and API request validation. `hostname_of` mirrors
`models.website.hostname_of` (kept there rather than imported from
here, since that copy's docstring — "mirrors Utils.hostnameOf on the
frontend" — predates this module and models/ shouldn't depend on
utils/ for one three-line function); everything else here is new
surface area for crawler/links/seo modules to reach for instead of
re-deriving URL logic per-file.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

_SCHEME_RE_PREFIX = ("http://", "https://")

# Common tracking params stripped by `strip_tracking_params` — analytics
# noise that shouldn't affect "is this the same page" comparisons
# (crawler dedup, seo.canonical, links.internal).
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"fbclid", "gclid", "gclsrc", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src"}


def ensure_scheme(url: str, default_scheme: str = "https") -> str:
    """`example.com` -> `https://example.com`; leaves URLs that already
    have a scheme untouched. Input to most of the functions below, and
    handy for user-supplied URLs (api/audit.py) that may omit `https://`."""
    value = (url or "").strip()
    if not value:
        return value
    if "//" in value.split("?", 1)[0][:12]:
        return value
    return f"{default_scheme}://{value}"


def is_valid_url(url: str) -> bool:
    """True if `url` parses to an absolute http(s) URL with a hostname.
    Rejects `mailto:`, `javascript:`, relative paths, and bare hostnames
    without a scheme (run through `ensure_scheme` first if that's fine
    for the caller)."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def hostname_of(url: str) -> str:
    """Best-effort lowercase hostname, `www.` stripped. Accepts a bare
    hostname or a full URL. See module docstring re: models.website's
    identical copy."""
    parsed = urlparse(url if "//" in url else f"//{url}")
    host = (parsed.hostname or url or "").lower()
    return host[4:] if host.startswith("www.") else host


def root_domain(url: str) -> str:
    """Best-effort registrable domain (`blog.example.co.uk` -> `example.co.uk`).
    Heuristic (last two labels, or three for a couple of common two-part
    TLDs) rather than a full public-suffix-list lookup — good enough for
    "are these two hosts probably the same site" comparisons
    (links/external.py, seo/canonical.py), not for anything security-sensitive."""
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
    """True if both URLs share a registrable root domain — `is_internal_link`
    is the stricter exact-hostname version of this."""
    root_a, root_b = root_domain(url_a), root_domain(url_b)
    return bool(root_a) and root_a == root_b


def is_internal_link(link: str, base_url: str) -> bool:
    """True if `link` (absolute or relative) resolves to the same
    hostname as `base_url` — used by crawler/links.py and
    links/internal.py to classify links found on a crawled page."""
    resolved = urljoin(base_url, link)
    return hostname_of(resolved) == hostname_of(base_url)


def join_url(base: str, path: str) -> str:
    """Thin, explicitly-named wrapper over `urllib.parse.urljoin` for
    resolving a relative href/src against the page it was found on."""
    return urljoin(base, path)


def strip_tracking_params(url: str) -> str:
    """Removes utm_*/fbclid/gclid/etc. query params, preserving the rest
    in their original order. Used before treating two URLs as "the same
    page" for crawl deduplication and canonical-URL comparisons."""
    parsed = urlparse(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
        and not any(key.lower().startswith(p) for p in _TRACKING_PARAM_PREFIXES)
    ]
    return urlunparse(parsed._replace(query=urlencode(kept)))


def normalize_url(url: str, *, strip_fragment: bool = True, strip_trailing_slash: bool = True) -> str:
    """
    Canonicalizes a URL for comparison/dedup purposes:
      - lowercases scheme + host
      - strips tracking params (see `strip_tracking_params`)
      - drops the fragment (`#section`) by default
      - drops a trailing "/" from the path (except the root path itself)

    Not meant for display — only for "have we already crawled this page"
    style equality checks (crawler.py, sitemap.py).
    """
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
