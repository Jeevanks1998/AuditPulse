"""
services/audit_service.py

Business logic behind api/audit.py: the create flow, the query helpers
reused by dashboard_service / history_service / api/settings.py, stats
aggregation, and `run_audit_pipeline` — which crawls the audited URL once
and runs the real analytics/, consent/ and journey/ check
packages against it. It walks the same step sequence the frontend
already animates through (see config.constants.AUDIT_STEPS and
assets/js/audit.js) so the API and UI stay in lockstep, then persists
real scores/findings across every detail table: Issue rows (normalized
findings), Consent, and Analytics, plus a real AI-module pass via
services.ai_service.

Also links every audit to a Website row (models/website.py) so the same
hostname's runs can be grouped/trended, and logs a History event when an
audit starts and when it finishes or fails.

Nothing in this module imports from api/ or depends on FastAPI request
objects — routers call in, never the other way around, so this logic is
reusable from anywhere (api/audit.py, services.scheduler_service, a
future Celery beat worker, tests, ...).
"""

from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

import asyncio
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

# Only present in a given audit's real breakdown when the matching module
# was selected in its modules (see run_audit_pipeline) — kept here at 0
# purely so the empty/no-completed-audits stats shape from compute_stats()
# has a stable, predictable key set.
EMPTY_BREAKDOWN = {
    "consent": 0,
    "analytics": 0,
}


# --------------------------------------------------------------------------
# Query helpers (reused by dashboard_service / history_service / api/settings.py)
# --------------------------------------------------------------------------
async def get_recent_audits(db: AsyncSession, user: User, limit: int = 25) -> List[Audit]:
    result = await db.execute(
        select(Audit).where(Audit.user_id == user.id).order_by(Audit.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_all_audits(db: AsyncSession, user: User) -> List[Audit]:
    result = await db.execute(
        select(Audit).where(Audit.user_id == user.id).order_by(Audit.created_at.desc())
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
    avg_overall = round(sum(a.overall_score or 0 for a in completed) / len(completed))
    seo_issues = 0  # SEO module removed; retained for API backward compatibility.
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


# --------------------------------------------------------------------------
# Creation
# --------------------------------------------------------------------------
def new_audit(
    user_id: int,
    website_id: Optional[int],
    url: str,
    depth: str,
    max_pages: int,
    modules: list,
    target_region: Optional[str] = None,
) -> Audit:
    """Build (but don't add/persist) a queued Audit row."""
    # Drop modules that no longer exist (e.g. "performance" saved on an
    # older schedule) instead of failing; never leave an audit with no checks.
    modules = [m for m in (modules or []) if m in AUDIT_MODULES]
    if not any(m in CHECK_MODULES for m in modules):
        modules = modules + [m for m in CHECK_MODULES if m not in modules]
    return Audit(
        user_id=user_id,
        website_id=website_id,
        url=url,
        label="Full site" if depth == "full" else "Homepage",
        depth=depth,
        max_pages=max_pages,
        modules=modules,
        target_region=target_region,
        status="queued",
    )


async def start_audit(db: AsyncSession, user: User, payload: AuditCreate) -> Audit:
    """
    Full create flow for POST /audits/: resolve the Website row, persist
    the Audit, log an AUDIT_CREATED event, and commit. Does not start the
    background pipeline — the caller (api/audit.py) owns BackgroundTasks
    since that's a FastAPI request-scoped concern.
    """
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


# --------------------------------------------------------------------------
# Pipeline — crawls the audited URL once, then runs the real
# analytics/, and consent/ check packages against it.
# --------------------------------------------------------------------------
async def run_audit_pipeline(audit_id: int) -> None:
    """
    Runs in the background after an audit is created (via BackgroundTasks).
    Walks AUDIT_STEPS, persisting progress after each real check group
    completes, then finalizes with real scores across
    Audit.breakdown/findings plus the normalized Issue, Consent, and
    Analytics rows. Uses its own DB session since it runs outside request
    scope — never reuse a request-scoped session here.

    consent/analytics are optional modules (see config.constants.AUDIT_MODULES):
    when selected, their real check packages (consent/, analytics/) run as
    part of this same pipeline — sharing the page already crawled for
    checkCrawl rather than re-fetching — and their scores are folded into
    Audit.breakdown/overall_score exactly like every other module, not
    written on the side. Consent/Analytics rows are still persisted
    separately (they carry much more detail than a breakdown score),
    via _run_consent_checks/_run_analytics_checks below.
    """
    async with AsyncSessionLocal() as db:
        audit = await db.get(Audit, audit_id)
        if not audit:
            logger.warning(f"run_audit_pipeline: audit {audit_id} not found")
            return

        audit.status = "running"
        audit.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            # Fresh fetch every run: no HTTP cache is used and intermediaries
            # are asked not to serve a cached copy either.
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=20.0,
                headers={"User-Agent": DEFAULT_USER_AGENT, "Cache-Control": "no-cache", "Pragma": "no-cache"},
            ) as client:
                await _advance_step(db, audit, "checkCrawl")
                response = await client.get(audit.url)
                if response.status_code >= 400:
                    # Mirrors crawler.crawl_site's per-page status check —
                    # a non-2xx homepage fetch (site down, bot-blocking WAF,
                    # 404, 500, ...) must fail the audit outright rather than
                    # silently scoring whatever error-page body came back.
                    raise RuntimeError(
                        f"Failed to fetch {audit.url}: HTTP {response.status_code}"
                    )
                page = parse_html(audit.url, response.text)
                hostname = urlparse(audit.url).hostname or ""

                # consent/analytics/journey/ai are all optional modules
                # (see config.constants.AUDIT_MODULES / audit.html's
                # checkboxes) — each real check package is skipped entirely
                # when deselected.
                breakdown: dict = {}
                findings: list = []

                # consent/analytics reuse the page + response already fetched
                # above for checkCrawl rather than crawling the site again
                # (analytics additionally crawls the rest of the site itself,
                # only for "full" depth audits — see _run_analytics_checks_site).
                consent_row = None
                analytics_row = None
                consent_runtime_result = None

                if "consent" in (audit.modules or []):
                    await _advance_step(db, audit, "checkConsent")
                    consent_row, consent_findings, consent_score, consent_runtime_result = await _run_consent_checks(
                        audit, page, response, hostname
                    )
                    breakdown["consent"] = consent_score
                    findings += consent_findings

                if "analytics" in (audit.modules or []):
                    await _advance_step(db, audit, "checkAnalytics")
                    analytics_row, analytics_findings, analytics_score_val = await _run_analytics_checks_site(
                        client, audit, page, consent_runtime_result=consent_runtime_result
                    )
                    breakdown["analytics"] = analytics_score_val
                    findings += analytics_findings

                journey_row = None
                if "journey" in (audit.modules or []):
                    await _advance_step(db, audit, "checkJourney")
                    journey_row, journey_findings, journey_score = await _run_journey_checks(audit)
                    _backfill_analytics_from_journey(analytics_row, journey_row)
                    if journey_score is not None:
                        breakdown["journey"] = journey_score
                    findings += journey_findings

                overall = _compute_overall_score(breakdown)

                if "ai" in (audit.modules or []):
                    findings = findings + await ai_service.generate_ai_findings(audit.url, breakdown)

                await _advance_step(db, audit, "checkReport")

            # --- Core result: persisted first, in its own commit ---------
            # Everything the report page needs lives on the Audit row
            # itself (status, score, breakdown, findings), so commit that
            # before any secondary bookkeeping. A failure in the extras
            # below then can no longer roll the audit back to "running"/
            # "failed" and throw away a finished result.
            # Status stays "running" (99%) until the module rows below are
            # saved too. Marking it "completed" here let the report page load
            # before the Journey/Consent/Analytics rows existed, so it showed
            # "This audit didn't include the Customer Journey module" for a
            # journey that had in fact run (the row landed seconds later).
            audit.status = "running"
            audit.percent = 99
            audit.current_step = "checkReport"
            audit.overall_score = overall
            audit.breakdown = breakdown
            audit.findings = findings
            audit.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info(f"Audit {audit_id} results saved — overall {overall}; saving module details")

            # Plain values only from here on: a rollback() in a secondary
            # step expires every attribute on `audit`, and touching them
            # afterwards would trigger an async lazy-load (MissingGreenlet).
            audit_user_id = audit.user_id
            audit_url = audit.url
            audit_website_id = audit.website_id
            completed_at = audit.completed_at

            # --- Secondary writes: each isolated, best-effort -------------
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
                await sync_issues_from_findings(db, audit, findings)

            async def _consent() -> None:
                # Never keep a previous Consent result for this audit (e.g. a
                # re-run / worker retry): replace it with this scan's row.
                existing = await db.execute(select(Consent).where(Consent.audit_id == audit_id))
                for old_row in existing.scalars().all():
                    await db.delete(old_row)
                await db.flush()
                db.add(consent_row)

            async def _analytics() -> None:
                db.add(analytics_row)

            async def _journey() -> None:
                # A fresh scan replaces any earlier journey result for this audit.
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
                    description=f"Audit of {audit_url} completed — overall {overall}",
                    audit_id=audit_id,
                    meta={"overall_score": overall},
                )

            async def _report_cache() -> None:
                # Cached JSON/HTML/PDF exports were built from the previous
                # results — drop them so downloads reflect this scan.
                report_storage.invalidate(audit_id)

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

            # --- Now the report can be opened: every module row exists ----
            try:
                await db.execute(
                    sa_update(Audit).where(Audit.id == audit_id).values(status="completed", percent=100)
                )
                await db.commit()
                logger.info(f"Audit {audit_id} completed — overall {overall}")
            except Exception:  # noqa: BLE001
                await db.rollback()
                logger.exception(f"Audit {audit_id}: could not mark as completed")

            # Scheduled audit with email delivery on: send the chosen reports
            # to the schedule's recipients. Best-effort, never fails the audit.
            from services.scheduled_email import deliver_scheduled_report

            await deliver_scheduled_report(audit_id)

        except Exception as exc:  # noqa: BLE001 — persist failure, don't crash the worker
            logger.exception(f"Audit {audit_id} failed: {exc}")

            # If the failure happened inside/around a db.commit() above, the
            # session's transaction is now aborted — any further use of it
            # (including the commit below) raises PendingRollbackError unless
            # we roll back first. rollback() also expires every attribute on
            # `audit`, so pull the plain values we still need for logging
            # *before* touching the session, rather than reading audit.url /
            # audit.user_id afterwards (that would trigger an async lazy-load
            # outside a greenlet -> MissingGreenlet).
            audit_url = audit.url
            audit_user_id = audit.user_id

            try:
                await db.rollback()
                audit.status = "failed"
                # error_message is String(500) — an unbounded exception message
                # (Playwright/httpx/AI-provider errors can run long) previously
                # blew past that limit and made *this* commit fail too, which
                # left the audit stuck at its last successful step forever.
                audit.error_message = str(exc)[:500]
                await log_event(
                    db,
                    audit_user_id,
                    HistoryEventType.AUDIT_FAILED,
                    description=f"Audit of {audit_url} failed: {exc}"[:500],
                    audit_id=audit_id,
                )
                await db.commit()
            except Exception:
                # Last-resort safety net: never let a background task die
                # without at least trying to mark the audit failed. If even
                # this fails, roll back and force a bare-minimum status update
                # so the row can't be left stuck at "running" indefinitely.
                logger.exception(f"Audit {audit_id}: failed to persist failure state")
                try:
                    await db.rollback()
                    audit.status = "failed"
                    audit.error_message = "Audit failed; see server logs."
                    await db.commit()
                except Exception:
                    logger.exception(f"Audit {audit_id}: could not even persist minimal failure state")


def _compute_overall_score(breakdown: dict) -> int:
    """
    Weighted overall score per requirements §6.1: Analytics and Consent
    (backed by real runtime/browser evidence, not just markup detection —
    see §2) carry more weight than the purely-static checks. Only the
    modules actually present in this run's `breakdown` are weighted and
    summed, then renormalized against the total weight of just those
    modules so a partial module selection (e.g. "analytics" unchecked)
    still produces a proper 0-100 score instead of silently scoring the
    missing module as 0.
    """
    if not breakdown:
        return 0
    total_weight = 0.0
    weighted_sum = 0.0
    for module, score in breakdown.items():
        weight = MODULE_WEIGHTS.get(module, DEFAULT_MODULE_WEIGHT)
        weighted_sum += (score or 0) * weight
        total_weight += weight
    if total_weight <= 0:
        return round(sum(breakdown.values()) / len(breakdown))
    return round(weighted_sum / total_weight)


async def _advance_step(db: AsyncSession, audit: Audit, step_id: str) -> None:
    """Marks the given AUDIT_STEPS entry current and persists progress %."""
    index = next((i for i, step in enumerate(AUDIT_STEPS) if step["id"] == step_id), None)
    if index is not None:
        audit.current_step = step_id
        # 100% is reserved for status == "completed" (set once, in
        # run_audit_pipeline, in the same commit as the status flip), so
        # the last step ("Generating report") tops out at 95%.
        audit.percent = min(round(((index + 1) / len(AUDIT_STEPS)) * 100), 95)
        await db.commit()



async def _run_consent_checks(
    audit: Audit, page: ParsedPage, response: httpx.Response, hostname: Optional[str]
) -> tuple:
    """
    Real consent/cookie-banner scan: runs every check in consent/ against
    the page + response already fetched for checkCrawl (banner presence,
    button parity, consent mode, cookies, pre-consent behavior), plus —
    when Playwright is installed and settings.CRAWLER_ENABLE_RUNTIME_CHECKS
    is on — the live pre-consent network capture and the full
    Accept/Reject/Personalize click-through pass (consent.runtime), so
    behavior's verdict and the report's runtime evidence are backed by
    what the controls really do, not just what the markup claims.

    Returns (Consent row, findings, consent breakdown score, raw
    ConsentRuntimeResult|None). The fourth element is the *unserialized*
    runtime result (not the JSON dict on the row) — Phase 2.5's
    _run_analytics_checks_site needs the real before/after-consent
    request lists to correlate against detected analytics vendors, which
    the serialized dict already flattens into plain data. Degrades
    gracefully: any failure here yields a minimal "no scan" Consent row
    rather than raising, so one module failing never takes down the whole
    audit (same contract this pipeline already follows for AI).
    """
    try:
        page_cookies = parse_set_cookie_headers(
            response.headers.get_list("set-cookie"), source_url=audit.url
        )
        # Every consent scan is fresh: new scan id, new browser contexts, new
        # network capture, banner detection, control inventory, region
        # detection and screenshots — nothing from a previous scan is reused.
        scan_id = f"a{audit.id}-{consent_module.new_scan_id()}"
        result = await asyncio.wait_for(consent_module.analyze_site(
            audit.url,
            page,
            cookies=page_cookies,
            first_party_hostname=hostname or None,
            enable_live_checks=True,
            capture_screenshot=getattr(settings, "CRAWLER_ENABLE_SCREENSHOTS", False),
            enable_runtime_checks=getattr(settings, "CRAWLER_ENABLE_RUNTIME_CHECKS", True),
            # Optional override (e.g. "IN", "EU", "US-CA"); unset => region is
            # detected from site signals, and Unknown => regional compliance
            # "not assessed" (see consent.region).
            # Per-audit choice first, then the server-wide default.
            target_region=(getattr(audit, "target_region", None)
                           or getattr(settings, "CONSENT_TARGET_REGION", None) or None),
            scan_id=scan_id,
        ), timeout=int(getattr(settings, "MODULE_HARD_TIMEOUT_S", 300)))
        logger.info(
            f"_run_consent_checks: fresh consent scan {scan_id} for {audit.url} — region "
            f"{result.summary.detected_region} ({result.summary.region_confidence}), frameworks "
            f"{result.summary.applicable_frameworks or 'not determined'}, "
            f"{len(result.summary.consent_controls)} control(s)"
        )
        consent = Consent(audit_id=audit.id, **vars(result.summary))
        return consent, result.findings, result.score.overall, result.runtime_result
    except Exception as exc:  # noqa: BLE001 — a failed consent scan shouldn't fail the whole audit
        logger.warning(f"_run_consent_checks: consent scan failed for {audit.url}: {exc}")
        consent = Consent(audit_id=audit.id, has_cookie_banner=False, consent_score=0)
        return consent, [], 0, None


def _backfill_analytics_from_journey(analytics_row, journey_row) -> None:
    """When the Analytics module's own live browser check could not run
    (runtime_available False), use what the Customer Journey's browser pass
    actually observed: it loads every scanned page in a real browser with
    consent accepted and records each analytics hit with the same vendor
    classifier. A detected vendor seen there gets Page View = passed; one
    never seen on any page stays absent (the report shows it as Failed).
    Scroll / Click stay "not tested" — the journey doesn't run those.
    Clearly marked source="journey" so the report can say where it came from.
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
    """
    Customer Journey scan (journey/): renders the site, discovers every
    interactive element, classifies it, safely tests the important ones with
    before / highlighted / after screenshots, validates analytics per
    interaction, builds the journey map and QA findings. Respects the audit's
    own depth and max_pages. Fresh browser context every run; nothing from a
    previous scan is reused.

    Returns (Journey row, findings, journey score or None). Degrades
    gracefully like the other modules: a failure yields an "unavailable"
    row, never a failed audit.
    """
    import journey as journey_module
    from consent.runtime import new_scan_id

    scan_id = f"a{audit.id}-{new_scan_id()}"
    try:
        result = await asyncio.wait_for(
            journey_module.run_customer_journey(
                audit.url, max_pages=audit.max_pages or 10, depth=audit.depth or "homepage", scan_id=scan_id,
            ),
            timeout=int(getattr(settings, "JOURNEY_HARD_TIMEOUT_S", 480)),
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
        # Findings feed the shared Issues list (strip the heavy evidence blob).
        findings = [{k: v for k, v in f.items() if k != "journey"} | {
            "page": (f.get("journey") or {}).get("page"),
            "interaction": (f.get("journey") or {}).get("interaction"),
        } for f in result.findings]
        return row, findings, result.score
    except Exception as exc:  # noqa: BLE001 — a failed journey scan shouldn't fail the whole audit
        logger.warning(f"_run_journey_checks: journey scan failed for {audit.url}: {exc}")
        return Journey(audit_id=audit.id, available=False, error=str(exc)[:500], scan_id=scan_id), [], None


async def _run_analytics_checks_site(
    client: httpx.AsyncClient, audit: Audit, homepage_page: ParsedPage, consent_runtime_result=None
) -> tuple:
    """
    Real analytics/tag-detection + runtime-validation scan — the full
    Phase 1 + Phase 2 pipeline:

      - homepage: full analyze_site pass (every detector + the live
        Playwright Page View/Scroll/Click runtime pass, same as Phase 1).
      - "full" depth audits: additionally crawls the rest of the site via
        crawler.crawl_site (respecting the audit's own max_pages/URL
        scope/exclusions/duplicate handling — nothing about the crawl
        itself is reimplemented here) and runs a static-only analytics
        pass over every other crawled page (analyze_page_for_site) —
        see analyze_page_for_site's docstring for why runtime validation
        stays homepage-only.
      - cross-page consistency + site coverage are computed from those
        real per-page results, and the site-level score is derived from
        every page's actual findings, never just the homepage's.
      - when a consent runtime pass is available, correlates detected
        analytics vendors against consent's real before/after-consent
        network capture (Phase 2.5).

    Returns (Analytics row, findings, analytics breakdown score).
    Degrades gracefully, same contract as _run_consent_checks above —
    any failure in the extra full-site work falls back to the Phase 1
    homepage-only result rather than losing the whole module.
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
    )
    page_results = [homepage_page_result]

    if audit.depth == "full":
        try:
            # crawl_site is the single source of truth for *which* pages
            # belong to this site (crawl depth, max_pages, URL scope,
            # exclusions, and duplicate-URL handling all already applied
            # there — none of that is reimplemented here, per Phase 2.1).
            # Its PageResult only retains the lightweight PageSignals
            # extracted during the crawl, not the full ParsedPage/soup
            # each detect_*() needs, so each other page's HTML is fetched
            # once more here (same client, same pattern as the homepage
            # fetch above) purely to run the static analytics detectors
            # against it — the crawl itself is not repeated.
            crawl_result = await crawl_site(audit.url, max_pages=audit.max_pages, depth="full")
            for page_result in crawl_result.ok_pages:
                if page_result.url == audit.url:
                    continue  # homepage already analyzed above with the full runtime pass
                try:
                    page_response = await client.get(page_result.url)
                    if "text/html" not in page_response.headers.get("content-type", ""):
                        continue
                    parsed_page = parse_html(page_result.url, page_response.text)
                except Exception as page_exc:  # noqa: BLE001 — one unreachable page shouldn't drop the rest
                    logger.debug(
                        f"_run_analytics_checks_site: could not fetch {page_result.url} for analytics: {page_exc}"
                    )
                    continue
                site_page_result = analytics_module.analyze_page_for_site(parsed_page, page_result.url)
                page_results.append(site_page_result)
                findings += site_page_result.findings
        except Exception as exc:  # noqa: BLE001 — full-site analytics degrades to homepage-only, not a hard failure
            logger.warning(f"_run_analytics_checks_site: full-site crawl failed for {audit.url}: {exc}")

    cross_page_findings = analytics_module.check_cross_page_consistency(page_results) if len(page_results) > 1 else []
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

    site_coverage = analytics_module.compute_site_coverage(page_results, cross_page_findings) if len(page_results) > 1 else {}

    summary_kwargs = dict(vars(result.summary))
    summary_kwargs["analytics_score"] = score_val
    summary_kwargs["page_results"] = [dataclasses.asdict(p) for p in page_results] if len(page_results) > 1 else []
    summary_kwargs["site_coverage"] = site_coverage
    summary_kwargs["cross_page_findings"] = cross_page_findings

    analytics = Analytics(audit_id=audit.id, **summary_kwargs)
    return analytics, findings, score_val
