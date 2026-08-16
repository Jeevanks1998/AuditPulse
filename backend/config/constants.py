"""
config/constants.py

Static, non-secret constants shared across the backend. These mirror
`window.APP_CONFIG` in assets/js/config.js on the front end, so the two
stay in sync (module keys, audit steps, score bands, etc.).
"""

from enum import Enum

APP_NAME = "AuditPulse"

# Module keys — must match `data-module` attributes in audit.html
AUDIT_MODULES = [
    "ai",
    "pdf",
    "consent",
    "analytics",
    "performance",
    "accessibility",
    "seo",
]

# Ordered pipeline steps for a running audit job.
# `id` corresponds to the check-item element ids used by the frontend
# progress UI (assets/js/audit.js -> checkList).
AUDIT_STEPS = [
    {"id": "checkCrawl", "label": "Crawling website"},
    {"id": "checkSeo", "label": "SEO"},
    {"id": "checkAccessibility", "label": "Accessibility"},
    {"id": "checkPerformance", "label": "Performance"},
    {"id": "checkConsent", "label": "Cookie consent"},
    {"id": "checkAnalytics", "label": "Analytics"},
    {"id": "checkReport", "label": "Generating report"},
]

# Score-band thresholds shared by ring/chip coloring on the frontend.
SCORE_BANDS = {"good": 80, "mid": 50}

# Relative weighting for the overall score (requirements §6.1): the
# runtime-validated modules (Analytics, Consent — see analytics/runtime.py,
# consent/runtime.py) carry more weight than the purely-static checks,
# since a live pass/fail verdict is stronger signal than a heuristic scan.
# Keys match services.audit_service.EMPTY_BREAKDOWN / Audit.breakdown.
# services.audit_service._compute_overall_score only weights whichever
# modules actually ran for a given audit, renormalizing over their total
# weight — so this doesn't need to sum to 1.0 and new modules can be added
# here without updating every existing audit.
MODULE_WEIGHTS = {
    "seo": 0.10,
    "performance": 0.10,
    "accessibility": 0.10,
    "security": 0.10,
    "ux": 0.05,
    "images": 0.05,
    "links": 0.05,
    "mobile": 0.05,
    "forms": 0.05,
    "analytics": 0.15,
    "consent": 0.20,
}

# Fallback weight for any breakdown key not listed in MODULE_WEIGHTS above
# (e.g. a future module added to a check package before its weight is
# tuned here) — keeps _compute_overall_score from silently dropping it.
DEFAULT_MODULE_WEIGHT = 0.05


class AuditStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PASS = "pass"
    FAILED = "failed"
    COMPLETED = "completed"


class AuditDepth(str, Enum):
    HOMEPAGE = "homepage"
    FULL = "full"


class AuditLabel(str, Enum):
    HOMEPAGE = "Homepage"
    FULL_SITE = "Full site"


DEFAULT_MAX_PAGES = 50
MAX_PAGES_LIMIT = 1000
MIN_PAGES_LIMIT = 1

# Pagination defaults
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
