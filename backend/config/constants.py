"""
Shared constants. Keep in sync with window.APP_CONFIG in assets/js/config.js.
"""

from enum import Enum

APP_NAME = "AuditPulse"

# Module keys (match data-module in audit.html). analytics, consent and journey
# check the site; ai and pdf are report outputs.
AUDIT_MODULES = [
    "ai",
    "pdf",
    "consent",
    "analytics",
    "journey",      # Journey Map
]

# Modules that check the site.
CHECK_MODULES = ["analytics", "consent", "journey"]

# Audit progress steps, in order. `id` matches the progress list in assets/js/audit.js.
AUDIT_STEPS = [
    {"id": "checkCrawl", "label": "Crawling website"},
    {"id": "checkConsent", "label": "Cookie consent"},
    {"id": "checkAnalytics", "label": "Analytics"},
    {"id": "checkJourney", "label": "Journey map"},
    {"id": "checkReport", "label": "Generating report"},
]

# Score bands: 80+ Healthy, 50-79 Needs attention, below 50 Issues found.
SCORE_BANDS = {"good": 80, "mid": 50}

# Weights for the overall score. Consent counts most (checked in a real
# browser). Only modules that ran are averaged, so these needn't sum to 1.
# Keep in sync with assets/js/score-help.js and pdf/scoring.py.
MODULE_WEIGHTS = {
    "analytics": 0.15,
    "consent": 0.20,
    "journey": 0.15,
}

# Weight for any module not listed above.
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
