"""
consent/site_evidence.py

A few pages beyond the homepage, read once per consent scan, for two
purposes:

  1. Region detection (consent/region.py). Global ".com" sites rarely say
     where they operate on the homepage — axagbs.com is a typical case:
     the homepage is generic, but its policies page links an Indian
     Companies Act filing (Form MGT-7), its news URLs say "...in-pune..."
     and "...30-years-in-india". Reading the linked policy / legal / about /
     contact pages and the homepage's link URLs surfaces that evidence.

  2. Regional notice checks (consent/consent_score.py). The DPDP Act's
     notice requirements (purpose, grievance contact, rights) can only be
     judged from the privacy notice itself, which is often a separate page
     or a PDF.

Strictly read-only and bounded: at most MAX_PAGES fetches, each with a
short timeout and a size cap; any failure just means less evidence, never
an error.
"""

from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from config.logging import logger

MAX_PAGES = 6
FETCH_TIMEOUT_S = 10.0
MAX_BYTES = 4 * 1024 * 1024
MAX_PDF_PAGES = 40
TOTAL_BUDGET_S = 30.0
MAX_TEXT_CHARS = 200_000

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 AuditPulse")

# Which links are worth reading, best first.
_NOTICE_RE = re.compile(r"privacy|data[-_ ]?protection|personal[-_ ]?data|privacy[-_ ]?notice|datenschutz", re.I)
_POLICY_RE = re.compile(r"cookie|polic(?:y|ies)|legal|terms|disclaimer|imprint|impressum|grievance", re.I)
_ABOUT_RE = re.compile(r"about|contact|company|who[-_ ]we[-_ ]are|offices?|locations?|investor", re.I)


@dataclass
class SiteDocument:
    url: str
    kind: str          # "notice" | "policy" | "about" | "document"
    text: str
    is_pdf: bool = False


@dataclass
class SiteEvidence:
    documents: List[SiteDocument] = field(default_factory=list)
    link_urls: List[str] = field(default_factory=list)     # every homepage link (absolute)
    link_texts: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def notice(self) -> Optional[SiteDocument]:
        """The privacy notice, when one was read."""
        for d in self.documents:
            if d.kind == "notice":
                return d
        return None

    @property
    def notice_text(self) -> str:
        return " ".join(d.text for d in self.documents if d.kind == "notice")


def _short(url: str) -> str:
    p = urlparse(url)
    return (p.path or "/")[-60:]


def _candidates(base_url: str, page) -> Tuple[List[Tuple[int, str, str]], List[str], List[str]]:
    host = (urlparse(base_url).hostname or "").lower().removeprefix("www.")
    ranked: List[Tuple[int, str, str]] = []
    urls: List[str] = []
    texts: List[str] = []
    seen = set()
    for a in getattr(page, "anchor_tags", [])[:1500]:
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        if not absolute.startswith(("http://", "https://")):
            continue
        text = a.get_text(" ", strip=True) or ""
        urls.append(absolute)
        if text:
            texts.append(text)
        key = absolute.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        link_host = (urlparse(absolute).hostname or "").lower().removeprefix("www.")
        is_pdf = urlparse(absolute).path.lower().endswith(".pdf")
        same_site = link_host == host or link_host.endswith("." + host)
        if not same_site and not is_pdf:
            continue
        hay = f"{text} {urlparse(absolute).path}"
        if _NOTICE_RE.search(hay):
            ranked.append((0, key, "notice"))
        elif _POLICY_RE.search(hay):
            ranked.append((1, key, "policy"))
        elif _ABOUT_RE.search(hay):
            ranked.append((2, key, "about"))
    ranked.sort(key=lambda r: r[0])
    return ranked, urls, texts


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # optional dependency
    except Exception:  # noqa: BLE001
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for i, pg in enumerate(reader.pages):
            if i >= MAX_PDF_PAGES:
                break
            parts.append(pg.extract_text() or "")
        return " ".join(parts)
    except Exception:  # noqa: BLE001 — encrypted / malformed PDF
        return ""


async def _fetch(client, url: str) -> Tuple[str, List[str], List[str], bool]:
    """Returns (text, link_urls, link_texts, is_pdf). Empty text on any failure."""
    from crawler.parser import parse_html

    async with client.stream("GET", url) as resp:
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}")
        ctype = (resp.headers.get("content-type") or "").lower()
        chunks, size = [], 0
        async for chunk in resp.aiter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
    if "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf"):
        return _pdf_text(data)[:MAX_TEXT_CHARS], [], [], True
    html = data.decode("utf-8", errors="replace")
    parsed = parse_html(url, html)
    links = [urljoin(url, (a.get("href") or "")) for a in parsed.anchor_tags[:800] if a.get("href")]
    ltexts = [a.get_text(" ", strip=True) for a in parsed.anchor_tags[:800]]
    return (parsed.text_content or "")[:MAX_TEXT_CHARS], links, [t for t in ltexts if t], False


async def gather_site_evidence(base_url: str, page) -> SiteEvidence:
    """Read the privacy notice and a few policy/about pages linked from the homepage."""
    ranked, urls, texts = _candidates(base_url, page)
    ev = SiteEvidence(link_urls=urls, link_texts=texts)
    if not ranked:
        return ev
    try:
        import httpx
    except Exception:  # noqa: BLE001
        return ev

    picks: List[Tuple[str, str]] = []
    kinds_taken = {"notice": 0, "policy": 0, "about": 0}
    limits = {"notice": 2, "policy": 3, "about": 2}
    for _rank, url, kind in ranked:
        if kinds_taken[kind] >= limits[kind]:
            continue
        kinds_taken[kind] += 1
        picks.append((url, kind))
        if len(picks) >= MAX_PAGES:
            break

    async def run():
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, follow_redirects=True,
                                     headers={"User-Agent": _UA, "Accept-Language": "en"}) as client:
            for url, kind in picks:
                try:
                    text, links, ltexts, is_pdf = await _fetch(client, url)
                except Exception as exc:  # noqa: BLE001
                    ev.errors.append(f"{_short(url)}: {exc}"[:160])
                    continue
                ev.link_urls += links
                ev.link_texts += ltexts
                if text.strip():
                    # A policies page that is itself mostly links to PDFs: the
                    # notice may be one of those PDFs — read the first one.
                    ev.documents.append(SiteDocument(url=url, kind=kind, text=text, is_pdf=is_pdf))
                if kind != "notice" and not ev.notice and not is_pdf:
                    pdf = next((l for l in links
                                if l.lower().split("?")[0].endswith(".pdf") and _NOTICE_RE.search(l)), None)
                    if pdf:
                        try:
                            ptext, _, _, _ = await _fetch(client, pdf)
                            if ptext.strip():
                                ev.documents.append(SiteDocument(url=pdf, kind="notice", text=ptext, is_pdf=True))
                        except Exception as exc:  # noqa: BLE001
                            ev.errors.append(f"{_short(pdf)}: {exc}"[:160])

    try:
        await asyncio.wait_for(run(), timeout=TOTAL_BUDGET_S)
    except asyncio.TimeoutError:
        ev.errors.append("site evidence: time budget reached")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"site_evidence: {exc}")
    return ev


__all__ = ["SiteEvidence", "SiteDocument", "gather_site_evidence"]
