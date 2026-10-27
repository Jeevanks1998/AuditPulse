/*
 * HTTP client for the backend, exposed as window.Api.
 *
 * request() builds the URL from APP_CONFIG, adds the token, parses JSON, and on a
 * 401 clears the session and sends the user to login. It converts between
 * camelCase (frontend) and snake_case (backend). Namespaces: auth, settings,
 * audits, reports, history, scheduler, ai.
 * audits.run() starts an audit and polls until it finishes; reports.getFull()
 * combines the report with the AI endpoints.
 */

window.Api = (function () {
  var CFG = window.APP_CONFIG || {};
  var STORAGE_KEY = (CFG.STORAGE_KEYS && CFG.STORAGE_KEYS.SESSION) || 'auditpulse:session';

  /* Helpers */

  function isPlainObject(v) {
    return v !== null && typeof v === 'object' && !Array.isArray(v) && !(v instanceof Date);
  }

  function snakeToCamel(s) {
    return s.replace(/_([a-z0-9])/g, function (_, c) { return c.toUpperCase(); });
  }

  function camelToSnake(s) {
    return s.replace(/([A-Z])/g, function (_, c) { return '_' + c.toLowerCase(); });
  }

  // Keys whose inner keys are ids (e.g. GDPR check ids) and must stay as sent.
  var OPAQUE_KEYS = {
    gdpr_checks: true, ccpa_checks: true,
    // Check-id maps of evidence, kept as sent.
    gdpr_check_evidence: true, ccpa_check_evidence: true,
    // Consent region and technical scan: kept as sent.
    applicability: true, technical_scan: true,
    // Consent / Journey Map report views.
    report_view: true
  };

  function deepConvertKeys(value, convertKey, opaqueKeys) {
    if (Array.isArray(value)) return value.map(function (v) { return deepConvertKeys(v, convertKey, opaqueKeys); });
    if (isPlainObject(value)) {
      var out = {};
      Object.keys(value).forEach(function (k) {
        var convertedKey = convertKey(k);
        if (opaqueKeys && (opaqueKeys[k] || opaqueKeys[convertedKey])) {
          // Convert the key itself but leave the value's keys as the backend sent them.
          out[convertedKey] = value[k];
        } else {
          out[convertedKey] = deepConvertKeys(value[k], convertKey, opaqueKeys);
        }
      });
      return out;
    }
    return value;
  }

  function toCamel(value) { return deepConvertKeys(value, snakeToCamel, OPAQUE_KEYS); }
  function toSnake(value) { return deepConvertKeys(value, camelToSnake, OPAQUE_KEYS); }

  /* Session */

  function getSession() {
    try {
      var raw = window.sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function setSession(session) {
    try { window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session)); } catch (e) { /* ignore */ }
  }

  function clearSession() {
    try { window.sessionStorage.removeItem(STORAGE_KEY); } catch (e) { /* ignore */ }
  }

  function getToken() {
    var session = getSession();
    return session ? session.token : null;
  }

  function getUser() {
    var session = getSession();
    return session ? session.user : null;
  }

  function handleUnauthorized() {
    clearSession();
    if (window.AuthGuard && window.AuthGuard.onUnauthorized) {
      window.AuthGuard.onUnauthorized();
    } else {
      // No authguard.js on this page (e.g. the login page): just drop the stale session.
    }
  }

  /* Core fetch */

  function buildUrl(path) {
    var base = (CFG.API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '');
    return base + path;
  }

  function parseErrorMessage(status, body) {
    if (body && typeof body === 'object') {
      if (typeof body.detail === 'string') return body.detail;
      // errors come as { success: false, error: "..." }
      if (typeof body.error === 'string') return body.error;
      if (Array.isArray(body.detail) && body.detail[0] && body.detail[0].msg) return body.detail[0].msg;
    }
    return 'Request failed (' + status + ').';
  }

  // `raw: true` skips conversion and JSON parsing (for file downloads).
  function request(method, path, body, opts) {
    opts = opts || {};
    var token = getToken();
    var headers = {};
    if (token) headers['Authorization'] = 'Bearer ' + token;

    var fetchOpts = { method: method, headers: headers };

    if (body !== undefined && body !== null) {
      headers['Content-Type'] = 'application/json';
      fetchOpts.body = JSON.stringify(opts.raw ? body : toSnake(body));
    }

    return fetch(buildUrl(path), fetchOpts).then(function (res) {
      // `public: true` (sign-in steps): a 401 means wrong email / expired attempt, so show the message instead of redirecting.
      if (res.status === 401 && !opts.public) {
        handleUnauthorized();
        return Promise.reject(new Error('Your session has expired. Please sign in again.'));
      }

      if (res.status === 204) return null;

      if (opts.blob) {
        if (!res.ok) return Promise.reject(new Error('Request failed (' + res.status + ').'));
        return res.blob();
      }

      return res.text().then(function (text) {
        var data = null;
        if (text) {
          try { data = JSON.parse(text); } catch (e) { data = text; }
        }
        if (!res.ok) {
          return Promise.reject(new Error(parseErrorMessage(res.status, data)));
        }
        return opts.raw ? data : toCamel(data);
      });
    });
  }

  var get = function (path, opts) { return request('GET', path, null, opts); };
  var post = function (path, body, opts) { return request('POST', path, body, opts); };
  var patch = function (path, body, opts) { return request('PATCH', path, body, opts); };
  var del = function (path, opts) { return request('DELETE', path, null, opts); };
  var getBlob = function (path) { return request('GET', path, null, { blob: true }); };

  /* Auth */

  var auth = {
    // Sign-in step 1 (email). Returns { step: 'setup'|'verify', challengeToken, ... }; no session yet.
    login: function (email) {
      return post('/auth/login', { email: email }, { public: true });
    },

    // Sign-in step 2: the 6-digit code. Stores the session.
    verifyCode: function (challengeToken, code) {
      return post('/auth/verify', { challengeToken: challengeToken, code: code }, { public: true }).then(function (data) {
        setSession({ token: data.token, user: data.user });
        return data.user;
      });
    },

    logout: function () {
      return post('/auth/logout', null).then(function () {
        clearSession();
      }).catch(function () {
        // Always clear the session and go to login, even if the server call failed.
        clearSession();
      }).then(function () {
        window.location.href = 'internal-login.html';
      });
    },

    verifySession: function () {
      return get('/auth/me').then(function (user) {
        var session = getSession();
        if (session) setSession({ token: session.token, user: user });
        return user;
      });
    },

    getSession: getSession,
    getToken: getToken,
    getUser: getUser
  };

  /* Settings */

  var settingsApi = {
    get: function () { return get('/settings/'); },
    save: function (patch_) { return patch('/settings/', patch_); },
    regenerateApiKey: function () {
      return post('/settings/api-key/regenerate', null).then(function (data) { return data.apiKey; });
    },
    exportJson: function () { return get('/settings/export'); }
  };

  /* Audits */

  var AUDIT_POLL_INTERVAL_MS = 1500;
  // Failed polls allowed in a row before giving up, and the total wait limit.
  var AUDIT_POLL_MAX_ERRORS = 5;
  // 45 minutes: big full-site audits can take a long time.
  var AUDIT_POLL_TIMEOUT_MS = 45 * 60 * 1000;

  var audits = {
    // Starts an audit, polls until it finishes, then resolves with the report.
    // onProgress gets { percent, stepId, status, elapsedLabel } after each poll.
    // Rejects if the audit fails.
    run: function (config, onProgress) {
      var startedAt = Date.now();

      var body = {
        url: config.url,
        depth: config.depth,
        maxPages: config.maxPages,
        modules: config.modules
      };
      if (config.targetRegion) body.targetRegion = config.targetRegion;  // sent as target_region
      return post('/audits/', body).then(function (audit) {
        return new Promise(function (resolve, reject) {
          var consecutiveErrors = 0;

          function retryOrReject(err) {
            consecutiveErrors += 1;
            var expired = err && /session has expired/i.test(err.message || '');
            if (expired || consecutiveErrors > AUDIT_POLL_MAX_ERRORS) {
              reject(err);
            } else {
              setTimeout(poll, AUDIT_POLL_INTERVAL_MS * 2);
            }
          }

          function poll() {
            if (Date.now() - startedAt > AUDIT_POLL_TIMEOUT_MS) {
              reject(new Error('The audit is taking longer than expected. Check History for its result.'));
              return;
            }
            get('/audits/' + audit.id + '/progress').then(function (progress) {
              consecutiveErrors = 0;
              if (onProgress) {
                var elapsedSec = Math.round((Date.now() - startedAt) / 1000);
                onProgress({
                  percent: progress.percent,
                  stepId: progress.currentStep,
                  status: progress.status === 'running' ? 'running'
                    : progress.status === 'queued' ? 'queued'
                    : progress.status === 'failed' ? 'fail' : 'pass',
                  elapsedLabel: elapsedSec + 's'
                });
              }

              // Only the status decides when polling stops, never the percent.
              if (progress.status === 'completed') {
                audits.get(audit.id).then(function (finished) {
                  return reports.get(finished.id).then(function (report) {
                    report.id = finished.id;
                    resolve(report);
                  });
                }).catch(reject);
              } else if (progress.status === 'failed') {
                reject(new Error('The audit failed while running. Please try again.'));
              } else {
                setTimeout(poll, AUDIT_POLL_INTERVAL_MS);
              }
            }).catch(retryOrReject);
          }
          poll();
        });
      });
    },

    get: function (auditId) { return get('/audits/' + auditId); },
    getStats: function () { return get('/audits/stats'); },
    getRecent: function () { return get('/audits/recent'); },
    getConsent: function (auditId) { return get('/audits/' + auditId + '/consent'); },
    getAnalytics: function (auditId) { return get('/audits/' + auditId + '/analytics'); },
    getJourney: function (auditId) { return get('/audits/' + auditId + '/journey'); },
    // Cookie Scanner. raw: cookie names and category ids stay as sent.
    getCookies: function (auditId) { return get('/audits/' + auditId + '/cookies', { raw: true }); },
    exportCookiesCsvBlob: function (auditId) { return getBlob('/audits/' + auditId + '/cookies.csv'); }
  };

  /* Reports */

  var reports = {
    get: function (auditId) { return get('/reports/' + auditId); },

    // Combines the report with the four AI endpoints; any failure rejects (report.js then falls back to get()).
    getFull: function (auditId) {
      return Promise.all([
        reports.get(auditId),
        get('/ai/' + auditId + '/summary'),
        get('/ai/' + auditId + '/priorities'),
        get('/ai/' + auditId + '/business-impact'),
        get('/ai/' + auditId + '/action-plan')
      ]).then(function (results) {
        var report = results[0];
        // Unwrap each AI response ({summary} / {priorities} / {items}).
        var pick = function (obj, key) { return obj && typeof obj === 'object' && key in obj ? obj[key] : obj; };
        report.executiveSummary = pick(results[1], 'summary');
        report.priorities = pick(results[2], 'priorities');
        report.businessImpact = pick(results[3], 'items');
        report.actionPlan = results[4];
        return report;
      });
    },

    share: function (auditId) {
      return post('/reports/' + auditId + '/share', null).then(function (data) { return data.shareUrl; });
    },

    exportPdfBlob: function (auditId) { return getBlob('/reports/' + auditId + '/export'); },
    exportEvidenceZipBlob: function (auditId) { return getBlob('/reports/' + auditId + '/evidence.zip'); },

    // raw: the keys are attachment ids the backend matches on; converting them would drop attachments.
    getAttachmentChoices: function () { return get('/reports/email/attachment-choices', { raw: true }); },
    sendToPoc: function (auditId, payload) { return post('/reports/' + auditId + '/send', payload); },
    getEmailHistory: function (auditId) { return get('/reports/' + auditId + '/email-history'); },

    // Email History for the whole account: every send plus the stat counters.
    // listEmailHistory({ q, status, page, pageSize }) -> { total, page, pageSize, stats, items }
    listEmailHistory: function (params) {
      params = params || {};
      var parts = [];
      if (params.q) parts.push('q=' + encodeURIComponent(params.q));
      if (params.status) parts.push('status=' + encodeURIComponent(params.status));
      parts.push('page=' + (params.page || 1));
      parts.push('page_size=' + (params.pageSize || 25));
      return get('/reports/email/history?' + parts.join('&'));
    },

    // One sent email in full (for View and Resend).
    getEmailRecord: function (emailId) { return get('/reports/email/history/' + emailId); }
  };

  /* History */
  // GET /history/ can filter by status (email-reports.html lists completed audits only).
  var historyApi = {
    // list({ q, status, page, pageSize }) -> { total, page, pageSize, items: [audit] }
    list: function (params) {
      params = params || {};
      var parts = [];
      if (params.q) parts.push('q=' + encodeURIComponent(params.q));
      if (params.status) parts.push('status=' + encodeURIComponent(params.status));
      if (params.deleted) parts.push('deleted=true');
      parts.push('page=' + (params.page || 1));
      parts.push('page_size=' + (params.pageSize || 25));
      return get('/history/?' + parts.join('&'));
    },

    listActivity: function (params) {
      params = params || {};
      var parts = [];
      if (params.eventType) parts.push('event_type=' + encodeURIComponent(params.eventType));
      parts.push('page=' + (params.page || 1));
      parts.push('page_size=' + (params.pageSize || 25));
      return get('/history/activity?' + parts.join('&'));
    },

    get: function (auditId) { return get('/history/' + auditId); },
    // Soft delete: can be restored from "Deleted audits".
    remove: function (auditId) { return del('/history/' + auditId); },
    restore: function (auditId) { return post('/history/' + auditId + '/restore', {}); }
  };

  /* Scheduler */

  var scheduler = {
    list: function () { return get('/scheduler/'); },
    create: function (config) { return post('/scheduler/', config); },
    update: function (scheduleId, patchBody) { return patch('/scheduler/' + scheduleId, patchBody); },
    remove: function (scheduleId) { return del('/scheduler/' + scheduleId); },
    runNow: function (scheduleId) { return post('/scheduler/' + scheduleId + '/run-now', null); }
  };

  /* AI */

  var ai = {
    chat: function (auditId, question, history) {
      return post('/ai/' + auditId + '/chat', { question: question, history: history || [] })
        .then(function (data) { return data.answer; });
    }
  };

  return {
    auth: auth,
    settings: settingsApi,
    audits: audits,
    reports: reports,
    history: historyApi,
    scheduler: scheduler,
    ai: ai
  };
})();
