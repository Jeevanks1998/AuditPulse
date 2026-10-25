/* Shared settings for every page (window.APP_CONFIG). Loaded first. */

window.APP_CONFIG = {

  APP_NAME: 'AuditPulse',

  // Backend API address. Set window.__AUDITPULSE_API_BASE__ before this script to override.
  API_BASE_URL: window.__AUDITPULSE_API_BASE__ || 'http://localhost:8000/api/v1',

  // Backend address without /api/v1 (e.g. for /screenshots).
  get API_ORIGIN() {
    return this.API_BASE_URL.replace(/\/api\/v1\/?$/, '');
  },

  STORAGE_KEYS: {
    THEME: 'auditpulse:theme',
    SESSION: 'auditpulse:session',
    DB: 'auditpulse:db'
  },

  // Module keys (match data-module in audit.html)
  MODULES: ['ai', 'pdf', 'consent', 'analytics', 'journey'],

  // Audit steps in order (ids match the progress list in audit.html).
  AUDIT_STEPS: [
    { id: 'checkCrawl', label: 'Crawling website' },
    { id: 'checkConsent', label: 'Cookie consent' },
    { id: 'checkAnalytics', label: 'Analytics' },
    { id: 'checkJourney', label: 'Journey map' },
    { id: 'checkReport', label: 'Generating report' }
  ],

  // Score bands (same as backend config/constants.py)
  SCORE_BANDS: { good: 80, mid: 50 }
};
