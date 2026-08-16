/* ==========================================================================
   config.js — shared, static configuration used across every page.
   Loaded first; every other script reads from window.APP_CONFIG.
   ========================================================================== */

window.APP_CONFIG = {

  APP_NAME: 'AuditPulse',

  // Base URL of the FastAPI backend (see /backend). Override by setting
  // window.__AUDITPULSE_API_BASE__ before this script loads, e.g. for a
  // deployed backend on a different origin.
  API_BASE_URL: window.__AUDITPULSE_API_BASE__ || 'http://localhost:8000/api/v1',

  // Backend origin with the /api/v1 suffix stripped — used for anything the
  // backend serves outside the API itself, e.g. the /screenshots static
  // mount (see backend/main.py) that consent-banner screenshots live under.
  get API_ORIGIN() {
    return this.API_BASE_URL.replace(/\/api\/v1\/?$/, '');
  },

  STORAGE_KEYS: {
    THEME: 'auditpulse:theme',
    SESSION: 'auditpulse:session',
    DB: 'auditpulse:db'
  },

  // Module keys correspond to the data-module attributes in audit.html
  MODULES: ['ai', 'pdf', 'consent', 'analytics', 'performance', 'accessibility', 'seo'],

  // Steps shown in the audit.html checklist / progress UI, in run order.
  // ids correspond to the check-item element ids in audit.html.
  AUDIT_STEPS: [
    { id: 'checkCrawl', label: 'Crawling website' },
    { id: 'checkSeo', label: 'SEO' },
    { id: 'checkAccessibility', label: 'Accessibility' },
    { id: 'checkPerformance', label: 'Performance' },
    { id: 'checkConsent', label: 'Cookie consent' },
    { id: 'checkAnalytics', label: 'Analytics' },
    { id: 'checkReport', label: 'Generating report' }
  ],

  // Score-band thresholds shared by ring/chip coloring
  SCORE_BANDS: { good: 80, mid: 50 }
};
