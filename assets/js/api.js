/* ==========================================================================
   api.js — the AuditPulse frontend's HTTP client. Exposed as window.Api.

   RECONSTRUCTED FILE — this previously contained a duplicate of
   authguard.js instead of the real API client, which meant window.Api
   never existed. Every protected page's authguard.js ran on load, found
   `!window.Api`, and called location.replace('internal-login.html') —
   including *while already on* internal-login.html, which is why that
   page reload-looped forever ("blinking") instead of rendering the form.

   Responsibilities:
     - One `request()` helper: builds the URL from window.APP_CONFIG,
       attaches the bearer token, parses JSON, and — on a 401 — clears
       the local session and routes through window.AuthGuard's
       onUnauthorized() (falls back to a direct redirect if authguard.js
       hasn't run on this page, e.g. internal-login.html itself).
     - camelCase <-> snake_case conversion at the request()/response
       boundary, since the backend's Pydantic schemas are snake_case
       (ai_provider, notify_audit_completed, current_step, ...) but every
       other frontend file (app.js, dashboard.js, audit.js, report.js,
       scheduler.js, history.js, permissions.js) reads/writes camelCase.
     - Session storage under APP_CONFIG.STORAGE_KEYS.SESSION.
     - Namespaced methods matching what those files already call:
       Api.auth, Api.settings, Api.audits, Api.reports, Api.history,
       Api.scheduler, Api.ai.

   Two spots are best-effort compositions rather than a 1:1 backend
   route, because the backend doesn't expose a single matching endpoint:
     - audits.run() starts an audit, polls /audits/{id}/progress, then
       fetches /reports/{id} once complete (see its comment below).
     - reports.getFull() merges /reports/{id} with the four /ai/{id}/*
       endpoints, matching report.js's own comment that getFull() is
       "the AI-enriched export" that can fail and fall back to get().
   If your backend already has different behavior for either of these,
   treat this file as a starting point, not gospel.
   ========================================================================== */

window.Api = (function () {
  var CFG = window.APP_CONFIG || {};
  var STORAGE_KEY = (CFG.STORAGE_KEYS && CFG.STORAGE_KEYS.SESSION) || 'auditpulse:session';

  /* ------------------------------ helpers ------------------------------ */

  function isPlainObject(v) {
    return v !== null && typeof v === 'object' && !Array.isArray(v) && !(v instanceof Date);
  }

  function snakeToCamel(s) {
    return s.replace(/_([a-z0-9])/g, function (_, c) { return c.toUpperCase(); });
  }

  function camelToSnake(s) {
    return s.replace(/([A-Z])/g, function (_, c) { return '_' + c.toLowerCase(); });
  }

  // Keys whose VALUE is a {checkId: result} map rather than a normal nested
  // object — the inner keys (consent_banner, accept_control,
  // trackers_blocked_pre_consent, privacy_policy_available, ...) are GDPR/CCPA
  // check ids that report.js's GDPR_CHECK_ITEMS / CCPA_CHECK_ITEMS look up
  // verbatim (mirroring the backend's consent.consent_score check order), so
  // they must survive untouched. Same reasoning as getAttachmentChoices'
  // `raw: true` below, just scoped to one field instead of the whole
  // response since the rest of the consent payload (gdprCompliant,
  // hasCookieBanner, ...) still needs the normal camelCase conversion.
  var OPAQUE_KEYS = {
    gdpr_checks: true, ccpa_checks: true,
    // gdpr_check_evidence/ccpa_check_evidence are {checkId: {summary, items,
    // items_label}} maps — same reasoning as gdpr_checks/ccpa_checks above,
    // the checkId keys are consent.consent_score.GDPR_CHECK_ORDER /
    // CCPA_CHECK_ORDER ids that report.js looks up verbatim.
    gdpr_check_evidence: true, ccpa_check_evidence: true
  };

  function deepConvertKeys(value, convertKey, opaqueKeys) {
    if (Array.isArray(value)) return value.map(function (v) { return deepConvertKeys(v, convertKey, opaqueKeys); });
    if (isPlainObject(value)) {
      var out = {};
      Object.keys(value).forEach(function (k) {
        var convertedKey = convertKey(k);
        if (opaqueKeys && (opaqueKeys[k] || opaqueKeys[convertedKey])) {
          // Convert the key itself (gdpr_checks -> gdprChecks) but leave the
          // value's own keys exactly as the backend sent them.
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

  /* ------------------------------ session ------------------------------- */

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
      // No authguard.js on this page (e.g. internal-login.html itself) —
      // nothing to bounce back from, so just make sure we're not holding
      // a stale session around.
    }
  }

  /* ------------------------------ core fetch ----------------------------- */

  function buildUrl(path) {
    var base = (CFG.API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '');
    return base + path;
  }

  function parseErrorMessage(status, body) {
    if (body && typeof body === 'object') {
      if (typeof body.detail === 'string') return body.detail;
      if (Array.isArray(body.detail) && body.detail[0] && body.detail[0].msg) return body.detail[0].msg;
    }
    return 'Request failed (' + status + ').';
  }

  // `raw: true` skips camelCase conversion and JSON parsing — used for blob
  // downloads (PDF export, evidence zip).
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
      if (res.status === 401) {
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

  /* -------------------------------- auth -------------------------------- */

  var auth = {
    login: function (email, password) {
      return post('/auth/login', { email: email, password: password }).then(function (data) {
        setSession({ token: data.token, user: data.user });
        return data.user;
      });
    },

    logout: function () {
      return post('/auth/logout', null).then(function () {
        clearSession();
      }).catch(function () {
        // Even if the server call fails (already-expired token, offline,
        // etc.), the person clicked "log out" — always drop the local
        // session and send them to login.
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

  /* ------------------------------ settings ------------------------------- */

  var settingsApi = {
    get: function () { return get('/settings/'); },
    save: function (patch_) { return patch('/settings/', patch_); },
    regenerateApiKey: function () {
      return post('/settings/api-key/regenerate', null).then(function (data) { return data.apiKey; });
    },
    exportJson: function () { return get('/settings/export'); }
  };

  /* ------------------------------- audits -------------------------------- */

  var AUDIT_POLL_INTERVAL_MS = 1500;
  // Consecutive failed polls tolerated before giving up (one dropped request
  // shouldn't abandon an audit that is still running server-side), and the
  // overall ceiling on how long we wait for a terminal status.
  var AUDIT_POLL_MAX_ERRORS = 5;
  var AUDIT_POLL_TIMEOUT_MS = 10 * 60 * 1000;

  var audits = {
    // Starts an audit, polls progress until it finishes, then resolves
    // with the finished report (id + overall + score grid + findings —
    // see reports.get()). onProgress(progress) is called after every
    // poll with { percent, stepId, status, elapsedLabel }, matching what
    // audit.js's updateProgressUi() expects. Rejects if the audit's
    // final status comes back "failed".
    run: function (config, onProgress) {
      var startedAt = Date.now();

      return post('/audits/', {
        url: config.url,
        depth: config.depth,
        maxPages: config.maxPages,
        modules: config.modules
      }).then(function (audit) {
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
                    : progress.status === 'failed' ? 'fail' : 'pass',
                  elapsedLabel: elapsedSec + 's'
                });
              }

              // Status alone decides when polling stops — never the percent.
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
    getRegionSummary: function () { return get('/audits/region-summary'); },
    getConsent: function (auditId) { return get('/audits/' + auditId + '/consent'); },
    getAnalytics: function (auditId) { return get('/audits/' + auditId + '/analytics'); }
  };

  /* ------------------------------- reports -------------------------------- */

  var reports = {
    get: function (auditId) { return get('/reports/' + auditId); },

    // The backend has no single "full" endpoint; this merges the plain
    // report with the four AI endpoints. Any one of them failing rejects
    // the whole thing, which is exactly what report.js wants — it
    // already falls back to reports.get() on rejection.
    getFull: function (auditId) {
      return Promise.all([
        reports.get(auditId),
        get('/ai/' + auditId + '/summary'),
        get('/ai/' + auditId + '/priorities'),
        get('/ai/' + auditId + '/business-impact'),
        get('/ai/' + auditId + '/action-plan')
      ]).then(function (results) {
        var report = results[0];
        report.executiveSummary = results[1];
        report.priorities = results[2];
        report.businessImpact = results[3];
        report.actionPlan = results[4];
        return report;
      });
    },

    share: function (auditId) {
      return post('/reports/' + auditId + '/share', null).then(function (data) { return data.shareUrl; });
    },

    exportPdfBlob: function (auditId) { return getBlob('/reports/' + auditId + '/export'); },
    exportEvidenceZipBlob: function (auditId) { return getBlob('/reports/' + auditId + '/evidence.zip'); },

    // `raw: true` because this response is a {key: label} map whose KEYS are
    // data, not field names: "consent_screenshots" is an attachment id the
    // backend matches on, and the usual snake->camel pass would rewrite it
    // to "consentScreenshots", which then round-trips back to POST /send as
    // a key emailer/attachments.py has never heard of — so the attachment is
    // silently dropped and the email goes out missing a file the user ticked.
    getAttachmentChoices: function () { return get('/reports/email/attachment-choices', { raw: true }); },
    sendToPoc: function (auditId, payload) { return post('/reports/' + auditId + '/send', payload); },
    getEmailHistory: function (auditId) { return get('/reports/' + auditId + '/email-history'); },

    // Account-wide Email History for email-reports.html. Unlike
    // getEmailHistory() above (one audit), this returns every send across
    // every audit plus the four unfiltered stat-card counters, so the page
    // costs one request instead of one per audit.
    // listEmailHistory({ q, status, page, pageSize })
    //   -> { total, page, pageSize, stats: { totalSent, successful, failed, reportsShared }, items: [...] }
    // Query params are built by hand — toSnake() only touches request bodies.
    listEmailHistory: function (params) {
      params = params || {};
      var parts = [];
      if (params.q) parts.push('q=' + encodeURIComponent(params.q));
      if (params.status) parts.push('status=' + encodeURIComponent(params.status));
      parts.push('page=' + (params.page || 1));
      parts.push('page_size=' + (params.pageSize || 25));
      return get('/reports/email/history?' + parts.join('&'));
    },

    // One recorded send, in full (recipients incl. bcc, subject, body,
    // attachment keys) — what "View" shows and what "Resend" prefills the
    // composer from.
    getEmailRecord: function (emailId) { return get('/reports/email/history/' + emailId); }
  };

  /* -------------------------------- history -------------------------------- */
  // GET /history/ is the only endpoint that can filter audits by status, which
  // is what email-reports.html needs (it only ever lists *completed* audits).
  // Query params are built by hand rather than run through toSnake(), which
  // only touches request *bodies*.
  var historyApi = {
    // list({ q, status, page, pageSize }) -> { total, page, pageSize, items: [audit] }
    list: function (params) {
      params = params || {};
      var parts = [];
      if (params.q) parts.push('q=' + encodeURIComponent(params.q));
      if (params.status) parts.push('status=' + encodeURIComponent(params.status));
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
    remove: function (auditId) { return del('/history/' + auditId); }
  };

  /* ------------------------------- scheduler ------------------------------ */

  var scheduler = {
    list: function () { return get('/scheduler/'); },
    create: function (config) { return post('/scheduler/', config); },
    update: function (scheduleId, patchBody) { return patch('/scheduler/' + scheduleId, patchBody); },
    remove: function (scheduleId) { return del('/scheduler/' + scheduleId); },
    runNow: function (scheduleId) { return post('/scheduler/' + scheduleId + '/run-now', null); }
  };

  /* ---------------------------------- ai ----------------------------------- */

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
