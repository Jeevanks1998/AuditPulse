"""
SSRF protection: audits may only reach public internet addresses.

Without it, an audit of http://localhost, http://169.254.169.254 (cloud
metadata) or an internal host would let a user read our private network.
Loopback, private, link-local, reserved and clearly internal host names
(localhost, *.internal, *.local) are refused for:
  - the audit URL (when created, and again when it runs)
  - every httpx request and redirect (GuardedTransport)
  - every request Chromium makes (install_browser_guard)
ALLOW_PRIVATE_NETWORK_TARGETS=true is only for local tests.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

from config.logging import logger
from config.settings import settings

_BLOCKED_SUFFIXES = (".internal", ".local", ".localhost", ".localdomain", ".lan", ".home", ".corp",
                     ".intranet", ".railway.internal")
_BLOCKED_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "metadata",
                  "metadata.google.internal", "instance-data"}
_ALLOWED_SCHEMES = {"http", "https"}

# hostname -> (expires_at, is_public)
_dns_cache: Dict[str, Tuple[float, bool]] = {}
_DNS_TTL_S = 300


class BlockedTargetError(ValueError):
    """The URL points at a non-public address."""


def _allowed_private() -> bool:
    return bool(getattr(settings, "ALLOW_PRIVATE_NETWORK_TARGETS", False))


def is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.strip("[]"))
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified
                or (isinstance(addr, ipaddress.IPv4Address) and addr in ipaddress.ip_network("100.64.0.0/10")))


def _name_blocked(host: str) -> bool:
    h = host.lower().rstrip(".")
    return h in _BLOCKED_NAMES or any(h.endswith(s) for s in _BLOCKED_SUFFIXES) or "." not in h


def _resolve_public(host: str) -> bool:
    """True only if every address the name resolves to is public."""
    now = time.monotonic()
    cached = _dns_cache.get(host)
    if cached and cached[0] > now:
        return cached[1]
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        ips = {i[4][0] for i in infos}
        ok = bool(ips) and all(is_public_ip(ip) for ip in ips)
    except (socket.gaierror, UnicodeError, OSError):
        ok = True   # can't resolve: nothing to reach; let the request fail normally
    _dns_cache[host] = (now + _DNS_TTL_S, ok)
    return ok


def host_is_public(host: Optional[str]) -> bool:
    if _allowed_private():
        return True
    if not host:
        return False
    host = host.strip("[]").lower()
    try:
        ipaddress.ip_address(host)
        return is_public_ip(host)
    except ValueError:
        pass
    if _name_blocked(host):
        return False
    return _resolve_public(host)


def check_url(url: str) -> None:
    """Raises BlockedTargetError unless `url` is http(s) to a public host."""
    p = urlparse(url)
    if p.scheme.lower() not in _ALLOWED_SCHEMES:
        raise BlockedTargetError("Only http:// and https:// websites can be audited.")
    if p.username or p.password:
        raise BlockedTargetError("Website addresses with a username or password can't be audited.")
    if not host_is_public(p.hostname):
        raise BlockedTargetError(
            "This address points to a private or internal network, which AuditPulse doesn't audit. "
            "Enter a public website address.")


def is_url_allowed(url: str) -> bool:
    try:
        check_url(url)
        return True
    except BlockedTargetError:
        return False


# httpx: every request and redirect goes through this transport
class GuardedTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if not await asyncio.to_thread(is_url_allowed, url):
            logger.warning(f"net_guard: blocked request to non-public address {request.url.host}")
            raise httpx.ConnectError(f"Blocked request to a non-public address: {request.url.host}",
                                     request=request)
        return await super().handle_async_request(request)


def guarded_async_client(**kwargs) -> httpx.AsyncClient:
    """httpx client that refuses private/internal addresses."""
    if _allowed_private():
        return httpx.AsyncClient(**kwargs)
    kwargs.setdefault("transport", GuardedTransport())
    return httpx.AsyncClient(**kwargs)


# Chromium: blocks non-public addresses. Other route handlers call route.fallback(), so this one decides last.
async def _browser_route(route) -> None:
    try:
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")):
            return await route.fallback()
        if await asyncio.to_thread(is_url_allowed, url):
            return await route.fallback()
        logger.warning(f"net_guard: browser blocked non-public request {urlparse(url).hostname}")
        await route.abort("blockedbyclient")
    except Exception:  # noqa: BLE001 — page closed / context gone
        pass


async def guard_context(context) -> None:
    if _allowed_private():
        return
    await context.route("**/*", _browser_route)


def install_browser_guard(browser):
    """Makes every new browser context use the guard."""
    if _allowed_private() or getattr(browser, "_ap_guarded", False):
        return browser
    orig_new_context = browser.new_context
    orig_new_page = browser.new_page

    async def new_context(*a, **k):
        ctx = await orig_new_context(*a, **k)
        await guard_context(ctx)
        return ctx

    async def new_page(*a, **k):
        ctx = await new_context(*a, **k)
        page = await ctx.new_page()
        return page

    browser.new_context = new_context
    browser.new_page = new_page
    browser._ap_guarded = True
    _ = orig_new_page
    return browser
