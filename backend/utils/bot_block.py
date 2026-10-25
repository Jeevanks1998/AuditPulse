"""
Detects when a site's bot protection (Imperva, Cloudflare, Akamai, DataDome,
PerimeterX, AWS WAF, Sucuri, F5) served a block or challenge page instead of
the site, so it isn't scored as the website (e.g. axa.ie gave "no banner,
no analytics, 0"). The result is "blocked", with the details the site owner
needs to allowlist us. Only strong vendor signatures count.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from config.logging import logger

# (vendor, pattern in the page, only on small pages)
_SIGNATURES = [
    ("Imperva (Incapsula)", re.compile(r"Incapsula incident ID|_Incapsula_Resource|Request unsuccessful\. Incapsula", re.I), False),
    ("Imperva Advanced Bot Protection", re.compile(r"<title>\s*Pardon Our Interruption", re.I), False),
    ("Cloudflare", re.compile(r"<title>\s*(Just a moment\.\.\.|Attention Required! \| Cloudflare)|cf-chl-(bypass|widget|opt)|Sorry, you have been blocked.{0,400}Cloudflare", re.I | re.S), True),
    ("Akamai", re.compile(r"errors\.edgesuite\.net|<title>\s*Access Denied\s*</title>.{0,600}Reference\s*#\d", re.I | re.S), True),
    ("DataDome", re.compile(r"(geo\.)?captcha-delivery\.com|<title>\s*DataDome", re.I), True),
    ("HUMAN (PerimeterX)", re.compile(r"px-captcha|Access to this page has been denied.{0,800}(PerimeterX|px-cdn|human)", re.I | re.S), True),
    ("AWS WAF", re.compile(r"awswaf|aws-waf-token|challenge\.js.{0,200}awswaf", re.I | re.S), True),
    ("Sucuri", re.compile(r"Sucuri WebSite Firewall", re.I), False),
    ("F5 BIG-IP ASM", re.compile(r"The requested URL was rejected\. Please consult with your administrator", re.I), False),
]
_INCIDENT_RE = re.compile(r"(?:incident[ _]id|Reference\s*#|support ID is:?|Ray ID:?)\s*[:=]?\s*([A-Za-z0-9.\-]{6,80})", re.I)
_CLIENT_IP_RE = re.compile(r"[?&]cip=([0-9a-fA-F:.]{7,45})")
_LINK_RE = re.compile(r"<a\s[^>]*href=", re.I)


@dataclass
class BotBlock:
    blocked: bool = False
    vendor: Optional[str] = None
    incident_id: Optional[str] = None
    client_ip: Optional[str] = None
    title: Optional[str] = None
    evidence: Optional[str] = None
    screenshot: Optional[str] = None
    checked: bool = False
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def detect_block(html: str, title: str = "") -> BotBlock:
    """Checks one page's HTML for a block page."""
    html = html or ""
    head = html[:200_000]
    small = len(_LINK_RE.findall(head)) <= 8
    for vendor, rx, needs_small in _SIGNATURES:
        m = rx.search(head) or (rx.search(f"<title>{title}</title>") if title else None)
        if m and (small or not needs_small):
            inc = _INCIDENT_RE.search(head)
            ip = _CLIENT_IP_RE.search(head)
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", head))[:300].strip()
            return BotBlock(blocked=True, vendor=vendor, incident_id=inc.group(1) if inc else None,
                            client_ip=ip.group(1) if ip else None, title=title or None, evidence=snippet,
                            checked=True)
    return BotBlock(blocked=False, checked=True)


async def browser_preflight(url: str, scan_id: str, wait_s: float = 15.0) -> BotBlock:
    """Loads the homepage in the audit browser, waiting up to `wait_s` for JavaScript challenges to clear."""
    from playwright.async_api import async_playwright

    from config.browser import goto_page, launch_chromium
    from config.settings import settings

    result = BotBlock()
    try:
        async with async_playwright() as pw:
            browser = await launch_chromium(pw)
            try:
                context = await browser.new_context(viewport={"width": 1366, "height": 900})
                page = await context.new_page()
                await goto_page(page, url, load_wait_ms=6_000)
                waited = 0.0
                while True:
                    try:
                        html = await page.content()
                        title = await page.title()
                    except Exception:  # noqa: BLE001 — navigating (challenge reload)
                        html, title = "", ""
                    result = detect_block(html, title)
                    if not result.blocked or waited >= wait_s:
                        break
                    await page.wait_for_timeout(3_000)
                    waited += 3.0
                if result.blocked:
                    out_dir = Path(settings.SCREENSHOT_DIR) / "blocked"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    shot = out_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', scan_id)}.png"
                    try:
                        await page.screenshot(path=str(shot), timeout=10_000)
                        result.screenshot = f"blocked/{shot.name}"
                    except Exception:  # noqa: BLE001
                        pass
                    result.notes.append(f"Still blocked after waiting {int(waited)} s for the challenge to clear.")
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 — preflight is advisory; modules still run
        logger.warning(f"bot_block: preflight failed for {url}: {exc}")
        return BotBlock(checked=False, notes=[f"Preflight could not run: {str(exc)[:160]}"])
    return result


def block_finding(url: str, b: BotBlock) -> dict:
    """The finding shown when a site blocked the audit."""
    who = b.vendor or "its bot protection"
    details = []
    if b.incident_id:
        details.append(f"incident ID {b.incident_id}")
    if b.client_ip:
        details.append(f"blocked IP {b.client_ip}")
    return {
        "module": "site_access",
        "category": "access",
        "severity": "critical",
        "title": f"Website blocked the audit ({who})",
        "description": (
            f"{url} answered AuditPulse's browser with a {who} block/challenge page instead of the website"
            + (f" ({', '.join(details)})" if details else "") + ". Consent, analytics and journey results "
            "could not be verified, so they are not scored — this is not a finding about the website itself. "
            f"To fix: ask the site owner to allowlist AuditPulse in {who}"
            + (f" (server IP {b.client_ip})" if b.client_ip else "") + ", then run the audit again."),
        "recommendation": (
            f"Ask the site owner to allowlist AuditPulse in {who} — by the server IP"
            + (f" {b.client_ip}" if b.client_ip else "") + " and/or the AuditPulse user agent — then run the "
            "audit again."),
        "affected_urls": [url],
        "evidence": {"bot_block": b.as_dict()},
    }
