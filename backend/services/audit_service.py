"""
services/audit_service.py

Business logic behind api/audit.py: the create flow, the query helpers
reused by dashboard_service / history_service / api/settings.py, stats
aggregation, and `run_audit_pipeline` — which crawls the audited URL once
and runs the real seo/, performance/, accessibility/, security/, ux/,
images/, links/, mobile/, forms/, analytics/, and consent/ check
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

import dataclasses
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import accessibility as accessibility_module
import analytics as analytics_module
import consent as consent_module
import forms as forms_module
import images as images_module
import links as links_module
import mobile as mobile_module
import performance as performance_module
import security as security_module
import seo as seo_module
import ux as ux_module
from config.constants import AUDIT_STEPS, DEFAULT_MODULE_WEIGHT, MODULE_WEIGHTS
from config.database import AsyncSessionLocal
from config.logging import logger
from config.settings import settings
from cookies.detector import parse_set_cookie_headers
from crawler.crawler import crawl_site
from crawler.links import extract_links
from crawler.parser import ParsedPage, parse_html
from crawler.robots import DEFAULT_USER_AGENT
from models.analytics import Analytics
from models.audit import Audit
from models.consent import Consent
from models.history import HistoryEventType, log_event
from models.issue import sync_issues_from_findings
from models.user import User
from models.website import Website, get_or_create_website, record_audit_result
from schemas.audit import AuditCreate, AuditStatsOut
from services import ai_service

EMPTY_BREAKDOWN = {
    "seo": 0,
    "performance": 0,
    "accessibility": 0,
    "security": 0,
    "ux": 0,
    "images": 0,
    "links": 0,
    "mobile": 0,
    "forms": 0,
    # Only present in a given audit's real breakdown when "consent"/
    # "analytics" were selected in its modules (see run_audit_pipeline) —
    # kept here at 0 purely so the empty/no-completed-audits stats shape
    # from compute_stats() has a stable, predictable key set.
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
            performance_score=0,
            critical_issues=0,
            overall=0,
            breakdown=dict(EMPTY_BREAKDOWN),
        )

    latest = completed[0]
    avg_overall = round(sum(a.overall_score or 0 for a in completed) / len(completed))
    seo_issues = sum(1 for a in completed for f in (a.findings or []) if f.get("module") == "seo")
    critical_issues = sum(
        1 for a in completed for f in (a.findings or []) if f.get("severity") == "critical"
    )

    return AuditStatsOut(
        total_audits=len(all_audits),
        seo_issues=seo_issues,
        performance_score=(latest.breakdown or {}).get("performance", 0),
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
) -> Audit:
    """Build (but don't add/persist) a queued Audit row."""
    return Audit(
        user_id=user_id,
        website_id=website_id,
        url=url,
        label="Full site" if depth == "full" else "Homepage",
        depth=depth,
        max_pages=max_pages,
        modules=modules,
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
    audit = new_audit(user.id, website.id, payload.url, payload.depth, payload.max_pages, payload.modules)
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
# Pipeline — crawls the audited URL once, then runs the real seo/,
# performance/, accessibility/, security/, analytics/, and consent/
# check packages against it.
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
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=20.0, headers={"User-Agent": DEFAULT_USER_AGENT}
            ) as client:
                await _advance_step(db, audit, "checkCrawl")
                response = await client.get(audit.url)
                page = parse_html(audit.url, response.text)
                hostname = urlparse(audit.url).hostname or ""
                links = extract_links(page, hostname)

                await _advance_step(db, audit, "checkSeo")
                seo_result = await _run_seo_checks(client, audit.url, page, links)

                await _advance_step(db, audit, "checkAccessibility")
                accessibility_result = await accessibility_module.run_accessibility_checks(client, page)

                await _advance_step(db, audit, "checkPerformance")
                performance_result = await performance_module.run_performance_checks(client, audit.url)
                security_result = await security_module.run_security_checks(client, page)

                ux_result = ux_module.score_ux(ux_module.run_page_checks(page))
                forms_result = forms_module.score_forms(forms_module.run_page_checks(page))
                mobile_result = mobile_module.run_mobile_checks(page, performance_result.metrics)

                images_findings = images_module.run_page_checks(page)
                images_findings += await images_module.run_site_checks(client, page)
                images_result = images_module.score_images(images_findings)

                links_findings = links_module.run_page_checks(page, links)
                links_findings += await links_module.run_site_checks(client, links)
                links_result = links_module.score_links(links_findings)

                breakdown = {
                    "seo": seo_result.overall,
                    "performance": performance_result.score.overall,
                    "accessibility": accessibility_result.score.overall,
                    "security": security_result.score.overall,
                    "ux": ux_result.overall,
                    "images": images_result.overall,
                    "links": links_result.overall,
                    "mobile": mobile_result.overall,
                    "forms": forms_result.overall,
                }

                findings: list = []
                findings += seo_result.findings
                findings += performance_result.findings
                findings += accessibility_result.findings
                findings += security_result.findings
                findings += ux_result.findings
                findings += images_result.findings
                findings += links_result.findings
                findings += mobile_result.findings
                findings += forms_result.findings

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

                overall = _compute_overall_score(breakdown)

                if "ai" in (audit.modules or []):
                    findings = findings + await ai_service.generate_ai_findings(audit.url, breakdown)

                await _advance_step(db, audit, "checkReport")

            audit.status = "completed"
            audit.overall_score = overall
            audit.breakdown = breakdown
            audit.findings = findings
            audit.completed_at = datetime.now(timezone.utc)

            await sync_issues_from_findings(db, audit, findings)

            if consent_row is not None:
                db.add(consent_row)
            if analytics_row is not None:
                db.add(analytics_row)

            if audit.website_id:
                website = await db.get(Website, audit.website_id)
                if website is not None:
                    await record_audit_result(website, overall, audit.completed_at)

            await log_event(
                db,
                audit.user_id,
                HistoryEventType.AUDIT_COMPLETED,
                description=f"Audit of {audit.url} completed — overall {overall}",
                audit_id=audit.id,
                meta={"overall_score": overall},
            )

            await db.commit()
            logger.info(f"Audit {audit_id} completed — overall {overall}")

        except Exception as exc:  # noqa: BLE001 — persist failure, don't crash the worker
            audit.status = "failed"
            audit.error_message = str(exc)
            await log_event(
                db,
                audit.user_id,
                HistoryEventType.AUDIT_FAILED,
                description=f"Audit of {audit.url} failed: {exc}",
                audit_id=audit.id,
            )
            await db.commit()
            logger.exception(f"Audit {audit_id} failed: {exc}")


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
        audit.percent = round(((index + 1) / len(AUDIT_STEPS)) * 100)
        await db.commit()


async def _run_seo_checks(
    client: httpx.AsyncClient, url: str, page: ParsedPage, links: list
) -> "seo_module.SEOScoreResult":
    """Runs every seo/ check (page-level + site-level, including a capped broken-link sample) and scores them."""
    findings = seo_module.run_page_checks(page, links)
    findings += await seo_module.run_site_checks(client, url, links_to_verify=links)
    return seo_module.score_seo(findings)


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
    audit (same contract this pipeline already follows for AI/SEO).
    """
    try:
        page_cookies = parse_set_cookie_headers(
            response.headers.get_list("set-cookie"), source_url=audit.url
        )
        result = await consent_module.analyze_site(
            audit.url,
            page,
            cookies=page_cookies,
            first_party_hostname=hostname or None,
            enable_live_checks=True,
            capture_screenshot=getattr(settings, "CRAWLER_ENABLE_SCREENSHOTS", False),
            enable_runtime_checks=getattr(settings, "CRAWLER_ENABLE_RUNTIME_CHECKS", True),
        )
        consent = Consent(audit_id=audit.id, **vars(result.summary))
        return consent, result.findings, result.score.overall, result.runtime_result
    except Exception as exc:  # noqa: BLE001 — a failed consent scan shouldn't fail the whole audit
        logger.warning(f"_run_consent_checks: consent scan failed for {audit.url}: {exc}")
        consent = Consent(audit_id=audit.id, has_cookie_banner=False, consent_score=0)
        return consent, [], 0, None


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
        result = await analytics_module.analyze_site(
            audit.url, homepage_page, enable_runtime_checks=getattr(settings, "CRAWLER_ENABLE_RUNTIME_CHECKS", True)
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
