"""
journey/ — Customer Journey Mapping (Phase 1: discovery, journey map,
evidence, tracking validation and journey QA).

AuditPulse is never told which buttons or journeys exist. It:

    scans the actual website (rendered, JavaScript executed)   journey_scanner
      → discovers what exists (every interactive element)
      → classifies it from multiple signals                    journey_interactions
      → understands page relationships                         journey_mapper
      → safely tests the important interactions                journey_interactions
      → captures before / highlighted / after evidence         journey_screenshots
      → validates analytics for each interaction               journey_tracking
      → builds the journey map and QA findings                 journey_mapper / journey_qa

The browser comes from analytics/runtime.py (open_runtime_browser) — the
same Playwright runtime the analytics module already uses — and the
consent banner is handled with consent/runtime.py's banner inventory, so no
second browser or banner implementation exists.

Production safety: forms are never submitted; purchases, payments,
bookings and sign-out/delete-type actions are never executed; external
links are checked by HTTP request instead of being followed.

Phase 2 (GA4 historical data, funnels, drop-offs) is intentionally not
implemented here yet.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from config.logging import logger
from config.settings import settings

from journey.journey_interactions import (
    CLASS_LABELS,
    Interaction,
    TestContext,
    build_interactions,
    select_for_testing,
    test_interaction,
)
from journey.journey_mapper import build_journey_map
from journey.journey_qa import build_findings, compute_health
from journey.journey_scanner import PageScan, ScanResult, normalize_url, scan_site
from journey.journey_screenshots import EvidenceWriter
from journey.journey_tracking import TrackingCapture, site_vendor_summary

__all__ = ["run_customer_journey", "JourneyResult", "CLASS_LABELS"]


@dataclass
class JourneyResult:
    available: bool = False
    error: Optional[str] = None
    scan_id: Optional[str] = None
    start_url: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    consent_state: str = "not_checked"
    tests_stopped_early: bool = False
    health: Dict[str, object] = field(default_factory=dict)
    pages: List[dict] = field(default_factory=list)
    interactions: List[dict] = field(default_factory=list)
    forms: List[dict] = field(default_factory=list)
    downloads: List[dict] = field(default_factory=list)
    journey_map: Dict[str, object] = field(default_factory=dict)
    tracking: Dict[str, object] = field(default_factory=dict)
    findings: List[dict] = field(default_factory=list)
    limits: Dict[str, object] = field(default_factory=dict)

    @property
    def score(self) -> Optional[int]:
        return (self.health or {}).get("score")

    def as_dict(self) -> dict:
        return asdict(self)


PER_TEST_TIMEOUT_S = 60


async def _accept_consent_if_present(page, result: JourneyResult) -> None:
    """Accept the cookie banner once so interactions are clickable and tags may fire."""
    try:
        from consent.buttons import ACCEPT_CLICK_ORDER
        from consent.runtime import _click_control, inventory_banner

        inv, handles = await inventory_banner(page)
        if not inv.banner_detected:
            result.consent_state = "no_banner"
            return
        accept = inv.first(ACCEPT_CLICK_ORDER)
        if accept is None:
            result.consent_state = "banner_without_accept"
            return
        ok = await _click_control(page, handles, accept)
        await page.wait_for_timeout(1_200)
        result.consent_state = f"accepted ({accept.label})" if ok else "accept_click_failed"
    except Exception as exc:  # noqa: BLE001
        result.consent_state = f"not_handled ({str(exc)[:80]})"


async def run_customer_journey(
    url: str,
    max_pages: int,
    depth: str,
    scan_id: str,
    max_tested: Optional[int] = None,
    max_tested_per_page: Optional[int] = None,
    test_interactions: Optional[bool] = None,
) -> JourneyResult:
    result = JourneyResult(scan_id=scan_id, start_url=url, started_at=datetime.now(timezone.utc).isoformat())
    max_tested = max_tested if max_tested is not None else int(getattr(settings, "JOURNEY_MAX_TESTED_INTERACTIONS", 30))
    per_page = max_tested_per_page if max_tested_per_page is not None else int(
        getattr(settings, "JOURNEY_MAX_TESTS_PER_PAGE", 8))
    do_tests = test_interactions if test_interactions is not None else bool(
        getattr(settings, "JOURNEY_ENABLE_INTERACTION_TESTS", True))
    host = urlparse(url).hostname or ""

    try:
        from crawler.screenshots import DEFAULT_VIEWPORT
        from journey.browser_session import JourneyBrowser, is_browser_dead_error
    except ImportError as exc:
        result.error = f"runtime unavailable: {exc}"
        return result

    evidence = EvidenceWriter(scan_id)
    capture = TrackingCapture()
    scan: Optional[ScanResult] = None
    interactions: List[Interaction] = []

    try:
        async with JourneyBrowser(capture=capture, viewport=DEFAULT_VIEWPORT) as session:
            async def on_first(page, _url):
                await _accept_consent_if_present(page, result)
                await session.save_state()  # a relaunch keeps the consent choice

            async def on_scanned(page, page_scan: PageScan):
                page_scan.screenshot = await evidence.page_snapshot(page, page_scan.url)

            scan_budget = int(getattr(settings, "JOURNEY_SCAN_BUDGET_S", 180))
            test_budget = int(getattr(settings, "JOURNEY_TEST_BUDGET_S", 180))
            scan = await scan_site(session, url, max_pages, depth, on_page_loaded=on_first,
                                   on_page_scanned=on_scanned, capture=capture,
                                   deadline=time.monotonic() + scan_budget)
            result.available = True
            interactions = build_interactions(scan.elements, scan.forms, host)
            analytics_present = bool(site_vendor_summary(capture)["analytics_present"])

            if do_tests:
                # Start the tests in a fresh Chromium: the scan's memory is
                # released, and the consent cookies carry over.
                await session.restart("fresh browser for interaction tests")
                session.restarts = 0  # the planned restart doesn't count against crash recovery
                page = await session.new_page()
                tc = TestContext(context=session.context, page=page, capture=capture, evidence=evidence,
                                 host=host, analytics_present=analytics_present)
                prefixes = {normalize_url(p.url): f"p{n + 1}e" for n, p in enumerate(scan.pages)}
                tests_deadline = time.monotonic() + test_budget
                for n, it in enumerate(select_for_testing(interactions, max_tested, per_page)):
                    if time.monotonic() > tests_deadline:
                        logger.info(f"journey: test time budget reached after {n} interaction(s)")
                        result.tests_stopped_early = True
                        break
                    prefix = prefixes.get(normalize_url(it.page_url), "pXe")
                    for attempt in range(2):
                        try:
                            await asyncio.wait_for(test_interaction(tc, it, prefix), timeout=PER_TEST_TIMEOUT_S)
                        except asyncio.TimeoutError:
                            it.status = "failed" if it.tested else "not_tested"
                            it.observed = it.observed or "Interaction test timed out (page did not respond)."
                            await session.restart("interaction test timed out")
                        dead = not session.alive() or is_browser_dead_error(it.observed)
                        if dead:
                            if not await session.restart(it.observed or "browser died during test"):
                                break
                        if dead or tc.page.is_closed() or (n + 1) % 6 == 0:
                            # New tab (and context after a restart); recycle every
                            # few tests so one tab doesn't accumulate memory.
                            try:
                                if not tc.page.is_closed():
                                    await tc.page.close()
                            except Exception:  # noqa: BLE001
                                pass
                            tc.page = await session.new_page()
                            tc.context = session.context
                        if not (dead and not it.tested and attempt == 0):
                            break
                        # Chromium died mid-test: run this interaction again once.
                        it.status, it.observed, it.outcome = "not_tested", "", None
                        it.screenshots = {}
                # Carry the tested result to repeats of the same element on other pages.
                by_index = {i.index: i for i in interactions}
                for it in interactions:
                    if it.duplicate_of is not None:
                        src = by_index.get(it.duplicate_of)
                        if src is not None and src.tested:
                            it.status = "same_as_first"
                            it.tracking = {"status": (src.tracking or {}).get("status"), "same_as": src.index}
    except Exception as exc:  # noqa: BLE001 — a failed journey scan never breaks the audit
        logger.warning(f"journey: customer journey scan failed for {url}: {exc}")
        result.error = str(exc)[:500]

    if scan is None:
        result.finished_at = datetime.now(timezone.utc).isoformat()
        return result

    analytics_summary = site_vendor_summary(capture)
    pages_meta = [{
        "url": p.url, "path": urlparse(p.url).path or "/", "title": p.title, "depth": p.depth,
        "parent": p.parent_url, "via": p.via_label, "status": p.status, "error": p.error,
        "elements": p.element_count, "forms": p.form_count, "screenshot": p.screenshot,
        "analytics_on_load": p.analytics_on_load, "loaded": p.error is None and (p.status or 200) < 400,
        "links_out": len(p.links_out),
    } for p in scan.pages]
    all_forms = [asdict(f) for f in scan.forms]
    forms_by_id = {f["id"]: f for f in all_forms}
    # The same form on every page (e.g. a header search box) is one form.
    forms_dicts, seen_sigs = [], set()
    for f in all_forms:
        key = f["signature"] or f["id"]
        if key in seen_sigs:
            continue
        seen_sigs.add(key)
        f["is_search"] = f.get("role") == "search" or any(
            (x.get("type") == "search" or (x.get("name") or "").lower() in ("q", "s", "query", "search"))
            for x in f["fields"])
        forms_dicts.append(f)

    page_shots = {normalize_url(p.url): p.screenshot for p in scan.pages}
    result.pages = pages_meta
    result.interactions = [i.as_dict() for i in interactions]
    result.forms = [{
        **{k: f[k] for k in ("id", "page_url", "name", "action", "method", "novalidate", "visible", "heading",
                             "role", "dynamic", "tracking_hints", "is_search")},
        "fields": [{k: x.get(k) for k in ("type", "name", "label", "required", "visible", "autocomplete", "pattern")}
                   for x in f["fields"]],
        "required_fields": sum(1 for x in f["fields"] if x.get("required")),
        "visible_fields": sum(1 for x in f["fields"] if x.get("visible")),
        "hidden_fields": sum(1 for x in f["fields"] if x.get("type") == "hidden"),
        "submit_controls": [s.get("text") for s in f["submits"]],
        "validation": ("browser validation disabled (novalidate)" if f["novalidate"] else
                       f"{sum(1 for x in f['fields'] if x.get('required'))} required, "
                       f"{sum(1 for x in f['fields'] if x.get('pattern'))} pattern-validated, "
                       f"{sum(1 for x in f['fields'] if x.get('type') in ('email', 'tel', 'url', 'number', 'date'))} typed"),
        "interaction_index": next((i.index for i in interactions if i.classification == "form" and i.form_id == f["id"]), None),
        "submission_tested": False,
    } for f in forms_dicts]
    result.downloads = [{
        "index": i.index, "label": i.label, "page_url": i.page_url, "destination": i.destination,
        "file_type": (urlparse(i.destination or "").path.rsplit(".", 1)[-1].lower()
                      if "." in urlparse(i.destination or "").path.rsplit("/", 1)[-1] else None),
        "http_status": i.http_status, "accessible": None if i.http_status is None else i.http_status < 400,
        "tested": i.tested, "tracking": (i.tracking or {}).get("status"),
        "screenshot": (i.screenshots or {}).get("highlighted"),
    } for i in interactions if i.classification == "download" and i.duplicate_of is None]
    result.journey_map = build_journey_map(scan.pages, interactions, page_shots, url)
    result.health = compute_health(interactions, len(scan.pages),
                                   len([f for f in forms_dicts if f["visible"] and not f["is_search"]]))
    result.tracking = {
        **analytics_summary,
        "coverage": {
            "tested": result.health["counts"]["interactions_tested"],
            "tracked": result.health["counts"]["tracked_interactions"],
            "gaps": result.health["counts"]["tracking_gaps"],
        },
    }
    result.findings = build_findings(interactions, pages_meta, bool(analytics_summary["analytics_present"]),
                                     forms_by_id)
    # Attach issue ids to map nodes.
    nodes = result.journey_map.get("nodes", {})
    for n, f in enumerate(result.findings):
        idx = (f.get("journey") or {}).get("interaction_index")
        if idx and f"int:{idx}" in nodes:
            nodes[f"int:{idx}"]["issues"].append(n)
    result.limits = {
        "depth": depth, "max_pages": max_pages, "page_limit": scan.page_limit,
        "pages_scanned": len(scan.pages), "max_tested_interactions": max_tested,
        "skipped_by_robots": scan.skipped_by_robots[:20], "interaction_tests_enabled": do_tests,
        "scan_stopped_by_time_budget": scan.stopped_early,
        "tests_stopped_by_time_budget": result.tests_stopped_early,
    }
    result.finished_at = datetime.now(timezone.utc).isoformat()
    return result
