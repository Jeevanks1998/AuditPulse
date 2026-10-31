"""
Audit logic: create and query audits, stats, and run_audit_pipeline(), which
fetches the site once and runs the analytics, consent and journey checks on
it, then saves scores, findings and module results. Each audit is linked to
a Website row and logged in History. No FastAPI imports, so it can be
reused anywhere.
"""

from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

import asyncio
import time
import dataclasses
import httpx
from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

import analytics as analytics_module
import consent as consent_module
from config.constants import AUDIT_MODULES, AUDIT_STEPS, CHECK_MODULES, DEFAULT_MODULE_WEIGHT, MODULE_WEIGHTS
from config.database import AsyncSessionLocal
from config.logging import logger
from config.settings import settings
from cookies.detector import parse_set_cookie_headers
from crawler.crawler import crawl_site
from crawler.parser import ParsedPage, parse_html
from crawler.robots import DEFAULT_USER_AGENT
from models.analytics import Analytics
from models.audit import Audit
from models.consent import Consent
from models.journey import Journey
from models.history import HistoryEventType, log_event
from models.issue import sync_issues_from_findings
from models.user import User
from models.website import Website, get_or_create_website, record_audit_result
from schemas.audit import AuditCreate, AuditStatsOut
from reports import report_storage
from services import ai_service
from utils.net_guard import guarded_async_client

# Zeros so empty stats always have the same keys.
EMPTY_BREAKDOWN = {
    "consent": 0,
    "analytics": 0,
}


# Queries (used by dashboard, history and settings)
async def get_recent_audits(db: AsyncSession, user: User, limit: int = 25) -> List[Audit]:
    result = await db.execute(
        select(Audit).where(Audit.user_id == user.id, Audit.deleted_at.is_(None))
        .order_by(Audit.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_all_audits(db: AsyncSession, user: User) -> List[Audit]:
    result = await db.execute(
        select(Audit).where(Audit.user_id == user.id, Audit.deleted_at.is_(None))
        .order_by(Audit.created_at.desc())
    )
    return list(result.scalars().all())


async def compute_stats(db: AsyncSession, user: User) -> AuditStatsOut:
    all_audits = await get_all_audits(db, user)
    completed = [a for a in all_audits if a.status == "completed"]

    if not completed:
        return AuditStatsOut(
            total_audits=len(all_audits),
            seo_issues=0,
            critical_issues=0,
            overall=0,
            breakdown=dict(EMPTY_BREAKDOWN),
        )

    latest = completed[0]
    scored = [a.overall_score for a in completed if a.overall_score is not None]
    avg_overall = round(sum(scored) / len(scored)) if scored else 0
    seo_issues = 0  # SEO module removed; kept for API compatibility.
    critical_issues = sum(
        1 for a in completed for f in (a.findings or []) if f.get("severity") == "critical"
    )

    return AuditStatsOut(
        total_audits=len(all_audits),
        seo_issues=seo_issues,
        critical_issues=critical_issues,
        overall=avg_overall,
        breakdown=latest.breakdown or dict(EMPTY_BREAKDOWN),
    )


# Creating audits
def new_audit(
    user_id: int,
    website_id: Optional[int],
    url: str,
    depth: str,
    max_pages: int,
    modules: list,
    target_region: Optional[str] = None,
) -> Audit:
    """Builds a queued Audit (doesn't save it)."""
    # Drop modules that no longer exist; never leave an audit with no checks.
    modules = [m for m in (modules or []) if m in AUDIT_MODULES]
    if not any(m in CHECK_MODULES for m in modules):
        # Standard audit = Analytics + Consent. The Journey Map only runs when asked for.
        modules = modules + [m for m in ("analytics", "consent") if m not in modules]
    return Audit(
        user_id=user_id,
        website_id=website_id,
        url=url,
        label=("Journey Map · " if [m for m in modules if m in CHECK_MODULES] == ["journey"] else "")
              + ("Full site" if depth == "full" else "Homepage"),
        depth=depth,
        max_pages=max_pages,
        modules=modules,
        target_region=target_region,
        status="queued",
    )


async def start_audit(db: AsyncSession, user: User, payload: AuditCreate) -> Audit:
    """Creates the audit (website row, Audit, history event). The caller starts the background pipeline."""
    website = await get_or_create_website(db, user.id, payload.url)
    audit = new_audit(
        user.id, website.id, payload.url, payload.depth, payload.max_pages, payload.modules,
        target_region=payload.target_region,
    )
    db.add(audit)
    await db.flush()

    await log_event(
        db,
        user.id,
        HistoryEventType.AUDIT_CREATED,
        description=f"Started {audit.label.lower()} audit of {audit.url}",
        audit_id=audit.id,
    )

    await db.commit()
    await db.refresh(audit)
    return audit


# Pipeline
# Longest an audit waits in the queue for the one before it (full-site audits take ~10 min).
AUDIT_QUEUE_MAX_WAIT_S = 45 * 60


async def run_audit_pipeline(audit_id: int) -> None:
    """Runs one audit at a time: if another is running, this one stays "queued" until it finishes."""
    from journey.run_lock import audit_slot

    async with audit_slot(max_wait_s=AUDIT_QUEUE_MAX_WAIT_S) as waited:
        if waited > 1:
            logger.info(f"Audit {audit_id}: waited {waited:.0f}s in the queue")
        await _run_audit_pipeline(audit_id)


async def _run_audit_pipeline(audit_id: int) -> None:
    """Runs in the background after an audit is created. Fetches the page once,
    runs each selected module on it, saves progress after each step, and saves
    the final scores, findings and module rows. Uses its own database session.
    """
    async with AsyncSessionLocal() as db:
        audit = await db.get(Audit, audit_id)
        if not audit:
            logger.warning(f"run_audit_pipeline: audit {audit_id} not found")
            return

        audit.status = "running"
        audit.started_at = datetime.now(timezone.utc)
        run_started_at = audit.started_at
        await db.commit()

        try:
            # Fresh fetch every time, no caches.
            async with guarded_async_client(
                follow_redirects=True, timeout=20.0,
                headers={"User-Agent": DEFAULT_USER_AGENT, "Cache-Control": "no-cache", "Pragma": "no-cache"},
            ) as client:
                await _advance_step(db, audit, "checkCrawl")
                # Check again now: DNS can change between scheduling and running (SSRF protection).
                from utils.net_guard import BlockedTargetError, check_url
                try:
                    check_url(audit.url)
                except BlockedTargetError as exc:
                    raise RuntimeError(str(exc)) from exc

                # Does the site let our browser in? Bot protection can serve a block page, which must not be scored as the site.
                site_block = None
                if settings.CRAWLER_ENABLE_RUNTIME_CHECKS and any(
                        m in (audit.modules or []) for m in ("consent", "analytics", "journey")):
                    from utils.bot_block import browser_preflight
                    site_block = await browser_preflight(audit.url, f"a{audit.id}-{int(time.time())}")
                    if site_block.blocked:
                        logger.warning(f"Audit {audit_id}: {audit.url} blocked the audit browser "
                                       f"({site_block.vendor}, incident {site_block.incident_id})")
                blocked = bool(site_block and site_block.blocked)

                response = None if blocked else await client.get(audit.url)
                if response is not None and response.status_code >= 400:
                    # A non-2xx homepage fails the audit instead of scoring an error page.
                    raise RuntimeError(
                        f"Failed to fetch {audit.url}: HTTP {response.status_code}"
                    )
                page = parse_html(audit.url, response.text) if response is not None else None
                hostname = urlparse(audit.url).hostname or ""

                # Each optional module is skipped entirely when not selected.
                breakdown: dict = {}
                findings: list = []
                if blocked:
                    from utils.bot_block import block_finding
                    findings.append(block_finding(audit.url, site_block))

                # Consent and analytics reuse the page already fetched (analytics crawls more pages for full-site audits).
                consent_row = None
                analytics_row = None
                consent_runtime_result = None

                if "consent" in (audit.modules or []) and not blocked:
                    await _advance_step(db, audit, "checkConsent")
                    consent_row, consent_findings, consent_score, consent_runtime_result = await _run_consent_checks(
                        audit, page, response, hostname
                    )
                    if consent_score is not None:
                        breakdown["consent"] = consent_score
                    findings += consent_findings

                if "analytics" in (audit.modules or []) and not blocked:
                    await _advance_step(db, audit, "checkAnalytics")
                    analytics_row, analytics_findings, analytics_score_val = await _run_analytics_checks_site(
                        client, audit, page, consent_runtime_result=consent_runtime_result
                    )
                    breakdown["analytics"] = analytics_score_val
                    findings += analytics_findings

                journey_row = None
                if "journey" in (audit.modules or []) and not blocked:
                    await _advance_step(db, audit, "checkJourney")
                    journey_row, journey_findings, journey_score = await _run_journey_checks(audit)
                    _backfill_analytics_from_journey(analytics_row, journey_row)
                    if journey_score is not None:
                        breakdown["journey"] = journey_score
                    findings += journey_findings

                # Findings the site's team marked "accepted" / "to verify" on earlier audits.
                raw_breakdown = None
                try:
                    from services.accepted_findings import apply_to_results, marks_for_website
                    marks = await marks_for_website(db, audit.website_id)
                    findings, breakdown, raw_breakdown = apply_to_results(
                        findings, breakdown, marks,
                        (journey_row.interactions if journey_row is not None else None))
                    if raw_breakdown and journey_row is not None:
                        from services.accepted_findings import apply_marks
                        journey_row.findings = apply_marks(journey_row.findings or [], marks)
                        if breakdown.get("journey") is not None:
                            journey_row.journey_score = breakdown["journey"]
                except Exception:  # noqa: BLE001 — marks never break an audit
                    logger.exception(f"Audit {audit_id}: could not apply accepted findings")
                overall = _compute_overall_score(breakdown)

                if "ai" in (audit.modules or []) and not blocked:
                    findings = findings + await ai_service.generate_ai_findings(audit.url, breakdown)

                await _advance_step(db, audit, "checkReport")

            # Save the main result first, in its own commit, so a later failure can't lose
            # it. Status stays "running" (99%) until the module rows are saved too, so the
            # report never opens before they exist.
            audit.status = "running"
            audit.percent = 99
            audit.current_step = "checkReport"
            audit.overall_score = overall
            audit.breakdown = breakdown
            audit.raw_breakdown = raw_breakdown
            audit.raw_overall_score = _compute_overall_score(raw_breakdown) if raw_breakdown else None
            audit.findings = findings
            audit.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(f"Audit {audit_id} results saved — overall {overall}; saving module details")

            # Plain values from here on: after a rollback, reading `audit` attributes would fail.
            audit_user_id = audit.user_id
            audit_url = audit.url
            audit_website_id = audit.website_id
            completed_at = audit.completed_at

            # Secondary writes: each separate and best-effort
            async def _secondary(label: str, work) -> None:
                try:
                    await work()
                    await db.commit()
                except Exception:  # noqa: BLE001
                    await db.rollback()
                    logger.exception(
                        f"Audit {audit_id}: completed, but secondary step '{label}' failed"
                    )

            async def _issues() -> None:
                from services.accepted_findings import active_findings
                await sync_issues_from_findings(db, audit, active_findings(findings))

            async def _consent() -> None:
                # Replace any earlier Consent row for this audit.
                existing = await db.execute(select(Consent).where(Consent.audit_id == audit_id))
                for old_row in existing.scalars().all():
                    await db.delete(old_row)
                await db.flush()
                db.add(consent_row)

            async def _analytics() -> None:
                db.add(analytics_row)

            async def _journey() -> None:
                # Replace any earlier Journey row for this audit.
                existing = await db.execute(select(Journey).where(Journey.audit_id == audit_id))
                for old_row in existing.scalars().all():
                    await db.delete(old_row)
                await db.flush()
                db.add(journey_row)

            async def _website() -> None:
                website = await db.get(Website, audit_website_id)
                if website is not None:
                    await record_audit_result(website, overall, completed_at)

            async def _history() -> None:
                await log_event(
                    db,
                    audit_user_id,
                    HistoryEventType.AUDIT_COMPLETED,
                    description=(f"Audit of {audit_url} completed — overall {overall}" if overall is not None
                                 else f"Audit of {audit_url} completed — not scored"),
                    audit_id=audit_id,
                    meta={"overall_score": overall},
                )

            async def _report_cache() -> None:
                # Drop cached exports built from the previous results.
                report_storage.invalidate(audit_id)

            async def _screenshots() -> None:
                # Copy screenshots to the database (the disk doesn't survive redeploys), before marking complete.
                from utils.screenshot_store import persist_new_screenshots
                await persist_new_screenshots(db, run_started_at)

            await _secondary("screenshots", _screenshots)
            await _secondary("report-cache", _report_cache)
            await _secondary("issues", _issues)
            if consent_row is not None:
                await _secondary("consent", _consent)
            if analytics_row is not None:
                await _secondary("analytics", _analytics)
            if journey_row is not None:
                await _secondary("journey", _journey)
            if audit_website_id:
                await _secondary("website", _website)
            await _secondary("history", _history)

            # Every module row exists: the report can open
            try:
                await db.execute(
                    sa_update(Audit).where(Audit.id == audit_id).values(status="completed", percent=100)
                )
                await db.commit()
                logger.info(f"Audit {audit_id} completed — overall {overall}")
            except Exception:  # noqa: BLE001
                await db.rollback()
                logger.exception(f"Audit {audit_id}: could not mark as completed")

            # Scheduled audit with email delivery: send the report. Never fails the audit.
            from services.scheduled_email import deliver_scheduled_report

            await deliver_scheduled_report(audit_id)

        except Exception as exc:  # noqa: BLE001 — persist failure, don't crash the worker
            logger.exception(f"Audit {audit_id} failed: {exc}")

            # Roll back a failed transaction first; read the values we need before that.
            audit_url = audit.url
            audit_user_id = audit.user_id
            reason = failure_reason(exc)

            try:
                await db.rollback()
                audit.status = "failed"
                # Cut the message to the column size, or this commit fails too.
                audit.error_message = reason[:500]
                await log_event(
                    db,
                    audit_user_id,
                    HistoryEventType.AUDIT_FAILED,
                    description=f"Audit of {audit_url} failed: {reason}"[:500],
                    audit_id=audit_id,
                )
                await db.commit()
            except Exception:
                # Last resort: always try to mark the audit failed so it can't stay "running".
                logger.exception(f"Audit {audit_id}: failed to persist failure state")
                try:
                    await db.rollback()
                    audit.status = "failed"
                    audit.error_message = "Audit failed; see server logs."
                    await db.commit()
                except Exception:
                    logger.exception(f"Audit {audit_id}: could not even persist minimal failure state")

    # Email the owner that the audit finished (Settings > "Audit completed"). Never raises.
    from services.audit_notify import notify_audit_finished

    await notify_audit_finished(audit_id)


def failure_reason(exc: BaseException) -> str:
    """A readable reason for a failed audit (network errors often have no message of their own)."""
    import httpx

    text = str(exc).strip()
    if isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)) or "reset by peer" in text.lower():
        return ("The website reset the connection from the AuditPulse server. Its bot protection may be "
                "blocking our server, often for a few hours after many audits in a row. Try again later.")
    if isinstance(exc, httpx.TimeoutException):
        return "The website did not respond in time. It may be down, very slow, or blocking our server."
    if isinstance(exc, httpx.ConnectError):
        return f"Could not connect to the website ({text or 'connection failed'})."
    return text or type(exc).__name__


def _same_page_key(url: Optional[str]) -> str:
    """Address of a page for de-duplicating: no fragment, no trailing slash, lower-case host."""
    from urllib.parse import urlsplit

    if not url:
        return ""
    try:
        from journey.journey_scanner import normalize_url   # drops campaign parameters (utm_*, gclid…)
        url = normalize_url(url)
    except Exception:  # noqa: BLE001
        pass
    p = urlsplit(url)
    path = p.path.rstrip("/")
    return f"{(p.hostname or '').lower()}{path}" + (f"?{p.query}" if p.query else "")


def _compute_overall_score(breakdown: dict) -> Optional[int]:
    """Overall score: weighted average of the modules that ran (weights in
    config/constants.py MODULE_WEIGHTS), so unselected modules don't count as 0.
    """
    if not breakdown:
        # Nothing scored (e.g. a journey with no testable interactions): "not scored", never 0.
        return None
    total_weight = 0.0
    weighted_sum = 0.0
    breakdown = {m: v for m, v in breakdown.items() if v is not None}
    if not breakdown:
        return None
    for module, score in breakdown.items():
        weight = MODULE_WEIGHTS.get(module, DEFAULT_MODULE_WEIGHT)
        weighted_sum += (score or 0) * weight
        total_weight += weight
    if total_weight <= 0:
        return round(sum(breakdown.values()) / len(breakdown))
    return round(weighted_sum / total_weight)


async def _advance_step(db: AsyncSession, audit: Audit, step_id: str) -> None:
    """Sets the current step and saves the progress %."""
    index = next((i for i, step in enumerate(AUDIT_STEPS) if step["id"] == step_id), None)
    if index is not None:
        audit.current_step = step_id
        # 100% only when completed, so the last step stops at 95%.
        audit.percent = min(round(((index + 1) / len(AUDIT_STEPS)) * 100), 95)
        await db.commit()


_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".doc", ".docx", ".xls",
             ".xlsx", ".ppt", ".pptx", ".mp4", ".mp3", ".ics", ".xml", ".json", ".css", ".js")


def _cookie_scan_urls(start_url: str, page, limit: int = 15) -> list:
    """Same-site pages linked from the homepage, in order, no duplicates."""
    from urllib.parse import urldefrag, urljoin

    host = (urlparse(start_url).hostname or "").lower()
    base = host[4:] if host.startswith("www.") else host
    out, seen = [], {start_url.rstrip("/")}
    for a in (getattr(page, "anchor_tags", None) or []):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urldefrag(urljoin(start_url, href))[0]
        p = urlparse(url)
        h = (p.hostname or "").lower()
        if p.scheme not in ("http", "https") or not (h == base or h.endswith("." + base)):
            continue
        if p.path.lower().endswith(_SKIP_EXT):
            continue
        key = url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
        if len(out) >= limit:
            break
    return out


async def _run_consent_checks(
    audit: Audit, page: ParsedPage, response: httpx.Response, hostname: Optional[str]
) -> tuple:
    """Runs the consent checks on the fetched page, plus the live browser checks
    when enabled. Returns (Consent row, findings, score, raw browser result).
    The raw result is used to match analytics tools against consent behaviour.
    Never raises: on failure returns a minimal "no scan" row.
    """
    try:
        page_cookies = parse_set_cookie_headers(
            response.headers.get_list("set-cookie"), source_url=audit.url
        )
        # Fresh scan every time: new scan id, browsers and screenshots.
        scan_id = f"a{audit.id}-{consent_module.new_scan_id()}"
        from consent.runtime import BROWSE_BUDGET_S
        # Cookie Scanner: for full-site audits, also visit up to 15 site pages after Accept.
        cookie_scan_urls = (_cookie_scan_urls(audit.url, page, limit=min(15, int(audit.max_pages or 15)))
                            if (audit.depth or "homepage") == "full" else [])
        result = await asyncio.wait_for(consent_module.analyze_site(
            audit.url,
            page,
            cookies=page_cookies,
            first_party_hostname=hostname or None,
            enable_live_checks=True,
            capture_screenshot=getattr(settings, "CRAWLER_ENABLE_SCREENSHOTS", False),
            enable_runtime_checks=getattr(settings, "CRAWLER_ENABLE_RUNTIME_CHECKS", True),
            # Region: the audit's choice, else the server default, else detect.
            target_region=(getattr(audit, "target_region", None)
                           or getattr(settings, "CONSENT_TARGET_REGION", None) or None),
            scan_id=scan_id,
            cookie_scan_urls=cookie_scan_urls,
        ), timeout=int(getattr(settings, "MODULE_HARD_TIMEOUT_S", 300))
           + (BROWSE_BUDGET_S + 30 if cookie_scan_urls else 0))
        logger.info(
            f"_run_consent_checks: fresh consent scan {scan_id} for {audit.url} — region "
            f"{result.summary.detected_region} ({result.summary.region_confidence}), frameworks "
            f"{result.summary.applicable_frameworks or 'not determined'}, "
            f"{len(result.summary.consent_controls)} control(s)"
        )
        consent = Consent(audit_id=audit.id, **vars(result.summary))
        # Not tested in a browser (site didn't open): no consent score rather than a false low one.
        score = result.score.overall if getattr(result, "browser_tested", True) else None
        return consent, result.findings, score, result.runtime_result
    except Exception as exc:  # noqa: BLE001 — a failed consent scan shouldn't fail the whole audit
        logger.warning(f"_run_consent_checks: consent scan failed for {audit.url}: {exc}")
        consent = Consent(audit_id=audit.id, has_cookie_banner=False, consent_score=0)
        return consent, [{"module": "consent", "category": "scan_coverage", "severity": "info",
                          "title": "Consent banner could not be tested in a browser",
                          "description": "The consent scan did not finish, so it is left out of the score. "
                                         f"Reason: {str(exc)[:200]}",
                          "recommendation": "Run the audit again."}], None, None


def _backfill_analytics_from_journey(analytics_row, journey_row) -> None:
    """If the analytics browser check couldn't run, use what the Journey Map's browser
    saw: tools seen there get Page View = passed. Scroll/Click stay "not tested".
    Marked source="journey".
    """
    try:
        if analytics_row is None or journey_row is None or getattr(analytics_row, "runtime_available", False):
            return
        if not getattr(journey_row, "available", False):
            return
        seen = {v.get("vendor"): v for v in ((journey_row.tracking or {}).get("vendors") or [])
                if v.get("vendor") and v.get("vendor") != "dataLayer" and (v.get("hits") or 0) > 0}
        detected = list((analytics_row.vendor_configs or {}).keys())
        if not detected:
            return
        from analytics.runtime import VENDOR_LABELS as RT_LABELS
        vendors = {}
        for key in detected:
            hit = seen.get(key)
            if not hit:
                continue
            events = sorted((hit.get("events") or {}).keys())
            vendors[key] = {
                "vendor_key": key, "vendor_name": RT_LABELS.get(key, key),
                "page_view_status": "passed", "scroll_status": "not_tested", "click_status": "not_tested",
                "custom_event_status": "not_applicable", "duplicate_page_view": False,
                "captured_request_count": int(hit.get("hits") or 0), "events_observed": events[:20],
                "source": "journey",
            }
        prev = dict(analytics_row.runtime_result or {})
        pages = len(journey_row.pages or [])
        prev.update({
            "available": True, "vendors": vendors, "source": "journey",
            "analytics_runtime_error": prev.get("error"),
            "note": (f"Taken from the Journey Map browser pass ({pages} page(s), consent accepted): "
                     "the Analytics module's own live check could not run."),
        })
        analytics_row.runtime_result = prev
        analytics_row.runtime_available = True
        analytics_row.runtime_tested = bool(vendors)
        logger.info(f"analytics: runtime evidence back-filled from journey — {sorted(vendors)} seen of {detected}")
    except Exception as exc:  # noqa: BLE001 — an optional enrichment never breaks the audit
        logger.warning(f"analytics: could not back-fill runtime from journey: {exc}")


async def _run_journey_checks(audit: Audit) -> tuple:
    """Runs the Journey Map (see journey/), within the audit's depth and page limit.
    Returns (Journey row, findings, score or None). Never fails the audit.
    """
    import journey as journey_module
    from consent.runtime import new_scan_id

    from journey.run_lock import journey_slot

    scan_id = f"a{audit.id}-{new_scan_id()}"
    hard_timeout = int(getattr(settings, "JOURNEY_HARD_TIMEOUT_S", 480))
    try:
        # One journey browser at a time (two can run out of memory). The time limit starts once this scan has the slot.
        async with journey_slot(max_wait_s=int(getattr(settings, "JOURNEY_LOCK_WAIT_S", 900))) as waited:
            if waited > 1:
                logger.info(f"_run_journey_checks: waited {waited:.0f}s for another journey scan to finish")
            # The runner stops itself just before the limit and keeps its results; wait_for is a last resort.
            soft_deadline = time.monotonic() + hard_timeout - 40
            result = await asyncio.wait_for(
                journey_module.run_customer_journey(
                    audit.url, max_pages=audit.max_pages or 10, depth=audit.depth or "homepage", scan_id=scan_id,
                    deadline=soft_deadline,
                ),
                timeout=hard_timeout + 60,
            )
        data = result.as_dict()
        row = Journey(
            audit_id=audit.id, available=result.available, error=(result.error or None),
            scan_id=scan_id, consent_state=(result.consent_state or "")[:120], journey_score=result.score,
            health=data["health"], pages=data["pages"], interactions=data["interactions"], forms=data["forms"],
            downloads=data["downloads"], journey_map=data["journey_map"], tracking=data["tracking"],
            findings=data["findings"], limits=data["limits"], started_at=result.started_at,
            finished_at=result.finished_at,
        )
        logger.info(
            f"_run_journey_checks: journey scan {scan_id} for {audit.url} — "
            f"{(result.health.get('counts') or {}).get('interactions_discovered', 0)} interactions, "
            f"{(result.health.get('counts') or {}).get('interactions_tested', 0)} tested, score {result.score}"
        )
        # Findings go to the shared issue list (without the heavy evidence).
        findings = [{k: v for k, v in f.items() if k != "journey"} | {
            "page": (f.get("journey") or {}).get("page"),
            "interaction": (f.get("journey") or {}).get("interaction"),
        } for f in result.findings]
        return row, findings, result.score
    except Exception as exc:  # noqa: BLE001 — a failed journey scan shouldn't fail the whole audit
        logger.warning(f"_run_journey_checks: journey scan failed for {audit.url}: {exc!r}")
        if isinstance(exc, asyncio.TimeoutError):
            message = (f"The journey scan did not finish within {round((hard_timeout + 60) / 60)} minutes "
                       "(the site was too slow to respond). Please run the audit again.")
        else:
            message = str(exc) or f"{type(exc).__name__} (no details)"
        return Journey(audit_id=audit.id, available=False, error=message[:500], scan_id=scan_id), [], None


async def _run_analytics_checks_site(
    client: httpx.AsyncClient, audit: Audit, homepage_page: ParsedPage, consent_runtime_result=None
) -> tuple:
    """Analytics checks: the homepage gets every detector plus the live browser
    check. Full-site audits also crawl the site and run static checks on each
    page, then check consistency across pages and site coverage. Matches tools
    against the consent results when available.
    Returns (Analytics row, findings, score). On failure in the full-site part,
    falls back to the homepage result.
    """
    try:
        result = await asyncio.wait_for(
            analytics_module.analyze_site(
                audit.url, homepage_page,
                enable_runtime_checks=getattr(settings, "CRAWLER_ENABLE_RUNTIME_CHECKS", True),
            ),
            timeout=int(getattr(settings, "MODULE_HARD_TIMEOUT_S", 300)),
        )
    except Exception as exc:  # noqa: BLE001 — a failed analytics scan shouldn't fail the whole audit
        logger.warning(f"_run_analytics_checks_site: analytics scan failed for {audit.url}: {exc}")
        analytics = Analytics(audit_id=audit.id)
        return analytics, [], 0

    findings = list(result.findings)
    homepage_page_result = analytics_module.PageAnalyticsResult(
        url=audit.url,
        trackers_detected=result.summary.trackers_detected,
        vendor_configs=result.summary.vendor_configs,
        score=result.score.overall,
        findings=result.findings,
        runtime_available=result.summary.runtime_available,
        runtime_tested=result.summary.runtime_tested,
        runtime_result=result.summary.runtime_result,
        title=((getattr(homepage_page, "title", None) or "").strip()[:200]),
        status_code=200,
        final_url=getattr(homepage_page, "url", None) or audit.url,
    )
    page_results = [homepage_page_result]

    if audit.depth == "full":
        try:
            # crawl_site decides which pages belong to the site; each page's HTML is fetched again here for the detectors.
            crawl_result = await crawl_site(audit.url, max_pages=audit.max_pages, depth="full")
            # Fetch the other pages in parallel.
            fetch_sem = asyncio.Semaphore(8)

            async def _fetch_and_analyze(page_url: str):
                async with fetch_sem:
                    try:
                        page_response = await client.get(page_url)
                        if "text/html" not in page_response.headers.get("content-type", ""):
                            return None
                        parsed_page = parse_html(page_url, page_response.text)
                    except Exception as page_exc:  # noqa: BLE001 — one unreachable page shouldn't drop the rest
                        logger.debug(f"_run_analytics_checks_site: could not fetch {page_url} for analytics: {page_exc}")
                        return None
                    res = analytics_module.analyze_page_for_site(parsed_page, page_url)
                    res.title = (parsed_page.title or "").strip()[:200]
                    res.status_code = page_response.status_code
                    res.final_url = str(page_response.url)
                    return res

            # Each page once: "https://site" and "https://site/" (or a redirect to a page already listed) are the same page.
            seen_pages = {_same_page_key(audit.url), _same_page_key(homepage_page_result.final_url)}
            other_urls = []
            for p in crawl_result.ok_pages:
                key = _same_page_key(p.url)
                if key not in seen_pages:
                    seen_pages.add(key)
                    other_urls.append(p.url)
            for site_page_result in await asyncio.gather(*(_fetch_and_analyze(u) for u in other_urls)):
                if site_page_result is None:
                    continue
                landed = _same_page_key(site_page_result.final_url)
                if landed != _same_page_key(site_page_result.url) and landed in seen_pages:
                    continue      # redirected to a page already listed
                seen_pages.add(landed)
                # Raw HTML with no tag at all can't prove a tag is missing (tag managers add tags in the
                # browser): "not verified", never "missing".
                if not site_page_result.trackers_detected:
                    site_page_result.not_verified = True
                page_results.append(site_page_result)
                findings += site_page_result.findings
        except Exception as exc:  # noqa: BLE001 — full-site analytics degrades to homepage-only, not a hard failure
            logger.warning(f"_run_analytics_checks_site: full-site crawl failed for {audit.url}: {exc}")

    # Compare like with like: the other pages were checked from their HTML only, so the homepage
    # takes part with what its HTML shows too (not the tags only seen in the live browser).
    comparable = page_results
    if len(page_results) > 1 and homepage_page is not None:
        try:
            home_static = analytics_module.analyze_page_for_site(homepage_page, audit.url)
            comparable = [dataclasses.replace(homepage_page_result, vendor_configs=home_static.vendor_configs,
                                              trackers_detected=home_static.trackers_detected,
                                              not_verified=not home_static.trackers_detected)] + page_results[1:]
        except Exception:  # noqa: BLE001
            comparable = page_results
    cross_page_findings = analytics_module.check_cross_page_consistency(comparable) if len(page_results) > 1 else []
    findings += cross_page_findings

    if consent_runtime_result is not None:
        findings += analytics_module.check_consent_analytics_correlation(
            result.summary.vendor_configs, consent_runtime_result, audit.url
        )

    if len(page_results) > 1:
        site_score = analytics_module.score_site_analytics(page_results, cross_page_findings)
        score_val = site_score.overall
    else:
        score_val = result.score.overall
    if not any(p.trackers_detected for p in page_results):
        score_val = 0      # no analytics anywhere on the site

    site_coverage = analytics_module.compute_site_coverage(page_results, cross_page_findings) if len(page_results) > 1 else {}

    summary_kwargs = dict(vars(result.summary))
    summary_kwargs["analytics_score"] = score_val
    summary_kwargs["page_results"] = [dataclasses.asdict(p) for p in page_results] if len(page_results) > 1 else []
    summary_kwargs["site_coverage"] = site_coverage
    summary_kwargs["cross_page_findings"] = cross_page_findings

    analytics = Analytics(audit_id=audit.id, **summary_kwargs)
    return analytics, findings, score_val
