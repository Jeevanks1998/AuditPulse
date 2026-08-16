/* ==========================================================================
   api.js — thin wrapper around the FastAPI backend (see /backend).
   Exposed as window.Api. Every other page script (auth.js, dashboard.js,
   history.js, audit.js, report.js, app.js's settings-page logic) calls
   through here rather than touching fetch()/localStorage directly.

   Handles: bearer-token session storage, JSON request/response plumbing,
   error normalization (so callers can just do `.catch(err => err.message)`),
   and mapping the backend's snake_case field names to the camelCase shape
   the rest of the frontend expects.
   ========================================================================== */

window.Api = (function () {
  var CFG = window.APP_CONFIG;
  var U = window.Utils;

  /* ---------------------------------------------------------------- */
  /* Session storage                                                    */
  /* ---------------------------------------------------------------- */

  function getSession() {
    return U.storageGetJSON(CFG.STORAGE_KEYS.SESSION, null);
  }

  function setSession(session) {
    U.storageSetJSON(CFG.STORAGE_KEYS.SESSION, session);
  }

  function clearSession() {
    U.storageRemove(CFG.STORAGE_KEYS.SESSION);
  }

  function getToken() {
    var s = getSession();
    return s ? s.token : null;
  }

  function getUser() {
    var s = getSession();
    return s ? s.user : null;
  }

  /* ---------------------------------------------------------------- */
  /* Core request helper                                                */
  /* ---------------------------------------------------------------- */

  function request(path, options) {
    options = options || {};
    var headers = { 'Content-Type': 'application/json' };
    var token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    Object.assign(headers, options.headers || {});

    return fetch(CFG.API_BASE_URL + path, {
      method: options.method || 'GET',
      headers: headers,
      body: options.body != null ? JSON.stringify(options.body) : undefined
    }).then(function (res) {
      if (res.status === 204) return null;

      var isJson = (res.headers.get('content-type') || '').indexOf('application/json') !== -1;

      return (isJson ? res.json() : res.text()).then(function (data) {
        if (!res.ok) {
          // Backend error shape is { success:false, error, details? } —
          // see backend/middleware/errors.py. `error` is the human-readable
          // message; `details` (validation errors) is an array, not a string.
          var message = (data && typeof data.error === 'string' && data.error)
            ? data.error
            : (typeof data === 'string' && data) || 'Something went wrong. Please try again.';
          if (res.status === 401) clearSession();
          throw new Error(message);
        }
        return data;
      });
    });
  }

  // For endpoints returning a binary body (PDF export) rather than JSON.
  function requestBlob(path) {
    var headers = {};
    var token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;

    return fetch(CFG.API_BASE_URL + path, { headers: headers }).then(function (res) {
      if (!res.ok) throw new Error('Could not generate the PDF export.');
      return res.blob();
    });
  }

  /* ---------------------------------------------------------------- */
  /* Field mapping — backend (snake_case) -> frontend (camelCase)      */
  /* ---------------------------------------------------------------- */

  function mapAudit(a) {
    if (!a) return a;
    return {
      id: a.id,
      url: a.url,
      label: a.label,
      depth: a.depth,
      status: a.status,
      currentStep: a.current_step,
      percent: a.percent,
      score: a.overall_score,
      breakdown: a.breakdown,
      createdAt: a.created_at,
      completedAt: a.completed_at
    };
  }

  function mapStats(s) {
    return {
      totalAudits: s.total_audits,
      seoIssues: s.seo_issues,
      performanceScore: s.performance_score,
      criticalIssues: s.critical_issues,
      overall: s.overall,
      breakdown: s.breakdown
    };
  }

  function mapConsent(c) {
    if (!c) return c;
    return {
      hasCookieBanner: c.has_cookie_banner,
      bannerBlocksScriptsPreConsent: c.banner_blocks_scripts_pre_consent,
      gdprCompliant: c.gdpr_compliant,
      ccpaCompliant: c.ccpa_compliant,
      privacyPolicyFound: c.privacy_policy_found,
      privacyPolicyUrl: c.privacy_policy_url,
      cookiesDetected: c.cookies_detected,
      thirdPartyTrackers: c.third_party_trackers,
      consentScore: c.consent_score,
      bannerScreenshotUrl: c.banner_screenshot_url,
      runtimeTested: c.runtime_tested,
      runtimeAvailable: c.runtime_available,
      preferencesScreenshotUrl: c.preferences_screenshot_url,
      rejectScreenshotUrl: c.reject_screenshot_url,
      acceptScreenshotUrl: c.accept_screenshot_url,
      runtimeResult: c.runtime_result
    };
  }

  function mapAnalytics(a) {
    if (!a) return a;
    return {
      trackersDetected: a.trackers_detected,
      tagManagerDetected: a.tag_manager_detected,
      gtmContainerId: a.gtm_container_id,
      gaMeasurementId: a.ga_measurement_id,
      vendorConfigs: a.vendor_configs,
      dataLayerPresent: a.data_layer_present,
      pageviewEventsFound: a.pageview_events_found,
      customEventsFound: a.custom_events_found,
      analyticsScore: a.analytics_score,
      runtimeTested: a.runtime_tested,
      runtimeAvailable: a.runtime_available,
      runtimeResult: a.runtime_result,
      // Phase 2 — full-site analytics. Empty list/dict defaults on a
      // homepage-only audit (see schemas.audit.AnalyticsOut); the
      // frontend reads that as "no full-site data" rather than "zero
      // pages have analytics".
      pageResults: a.page_results,
      siteCoverage: a.site_coverage,
      crossPageFindings: a.cross_page_findings
    };
  }

  function mapScoreCell(cell) {
    return { module: cell.module, label: cell.label, score: cell.score, targetSection: cell.target_section };
  }

  function mapReport(r) {
    if (!r) return r;
    return {
      auditId: r.audit_id,
      url: r.url,
      overall: r.overall,
      generatedAt: r.generated_at,
      scoreGrid: (r.score_grid || []).map(mapScoreCell),
      findings: r.findings || [],
      shareUrl: r.share_url
    };
  }

  function mapEmailSendResult(r) {
    if (!r) return r;
    return {
      success: r.success,
      status: r.status,
      errorMessage: r.error_message,
      sentAt: r.sent_at
    };
  }

  function mapEmailHistoryItem(h) {
    return {
      id: h.id,
      auditId: h.audit_id,
      to: h.recipient_to,
      cc: h.recipient_cc,
      subject: h.subject,
      status: h.status,
      sentAt: h.sent_at,
      errorMessage: h.error_message
    };
  }

  function mapSettings(s) {
    return {
      name: s.name,
      email: s.email,
      company: s.company,
      aiProvider: s.ai_provider,
      notifyAuditCompleted: s.notify_audit_completed,
      notifyCriticalIssue: s.notify_critical_issue,
      notifyWeeklySummary: s.notify_weekly_summary,
      theme: s.theme,
      language: s.language,
      scheduleFrequency: s.schedule_frequency,
      scheduleTime: s.schedule_time,
      apiKey: s.api_key
    };
  }

  function mapSchedule(s) {
    if (!s) return s;
    return {
      id: s.id,
      url: s.url,
      frequency: s.frequency,
      timeLabel: s.time_label,
      depth: s.depth,
      modules: s.modules || [],
      isActive: s.is_active,
      lastRunAt: s.last_run_at,
      nextRunAt: s.next_run_at
    };
  }

  function settingsPatchToBackend(patch) {
    var map = {
      name: 'name', email: 'email', company: 'company', aiProvider: 'ai_provider',
      notifyAuditCompleted: 'notify_audit_completed', notifyCriticalIssue: 'notify_critical_issue',
      notifyWeeklySummary: 'notify_weekly_summary', theme: 'theme', language: 'language',
      scheduleFrequency: 'schedule_frequency', scheduleTime: 'schedule_time'
    };
    var out = {};
    Object.keys(patch).forEach(function (key) {
      if (map[key] && patch[key] !== undefined) out[map[key]] = patch[key];
    });
    return out;
  }

  /* ---------------------------------------------------------------- */
  /* auth                                                                */
  /* ---------------------------------------------------------------- */

  var auth = {
    getSession: getSession,
    getUser: getUser,
    getToken: getToken,

    // Internal, passwordless login: email only, no password required.
    loginWithEmail: function (email) {
      return request('/auth/login-email', { method: 'POST', body: { email: email } })
        .then(function (data) {
          setSession({ token: data.token, user: data.user });
          return data.user;
        });
    },

    login: function (email, password) {
      return request('/auth/login', { method: 'POST', body: { email: email, password: password } })
        .then(function (data) {
          setSession({ token: data.token, user: data.user });
          return data.user;
        });
    },

    register: function (name, email, password, company) {
      return request('/auth/register', { method: 'POST', body: { name: name, email: email, password: password, company: company } })
        .then(function (data) {
          setSession({ token: data.token, user: data.user });
          return data.user;
        });
    },

    logout: function () {
      // Clear the local session immediately so any page that checks
      // getSession() right after (e.g. login.html's "already signed in"
      // redirect) sees a logged-out state, even if this tab navigates
      // away before the network call below finishes. Capture the token
      // first since clearSession() wipes it and request() can no longer
      // read it off the (now-cleared) session.
      var token = getToken();
      clearSession();
      if (!token) return Promise.resolve();
      return request('/auth/logout', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token }
      }).catch(function () {});
    }
  };

  /* ---------------------------------------------------------------- */
  /* audits                                                              */
  /* ---------------------------------------------------------------- */

  var POLL_INTERVAL_MS = 900;

  var audits = {
    getStats: function () {
      return request('/audits/stats').then(mapStats);
    },

    getRecent: function (limit) {
      return request('/audits/recent' + (limit ? ('?limit=' + encodeURIComponent(limit)) : ''))
        .then(function (list) { return list.map(mapAudit); });
    },

    getConsent: function (auditId) {
      return request('/audits/' + encodeURIComponent(auditId) + '/consent').then(mapConsent);
    },

    getAnalytics: function (auditId) {
      return request('/audits/' + encodeURIComponent(auditId) + '/analytics').then(mapAnalytics);
    },

    get: function (auditId) {
      return request('/audits/' + encodeURIComponent(auditId)).then(mapAudit);
    },

    // Starts an audit, polls its progress, and resolves with the finished
    // report once the pipeline completes. Calls onProgress({percent,
    // stepId, status, elapsedLabel}) after every poll.
    run: function (config, onProgress) {
      var body = {
        url: config.url,
        depth: config.depth,
        max_pages: config.maxPages,
        modules: config.modules
      };

      return request('/audits/', { method: 'POST', body: body }).then(function (created) {
        var auditId = created.id;
        var startedAt = Date.now();

        return new Promise(function (resolve, reject) {
          function poll() {
            request('/audits/' + auditId + '/progress').then(function (progress) {
              var elapsedSec = Math.round((Date.now() - startedAt) / 1000);
              if (onProgress) {
                onProgress({
                  percent: progress.percent,
                  stepId: progress.current_step,
                  status: progress.status === 'completed' || progress.status === 'failed' ? 'pass' : 'running',
                  elapsedLabel: elapsedSec + 's'
                });
              }

              if (progress.status === 'completed') {
                request('/reports/' + auditId).then(mapReport).then(function (report) {
                  resolve({ id: auditId, overall: report.overall, url: report.url });
                }).catch(reject);
              } else if (progress.status === 'failed') {
                reject(new Error('The audit failed while running. Please try again.'));
              } else {
                setTimeout(poll, POLL_INTERVAL_MS);
              }
            }).catch(reject);
          }
          poll();
        });
      });
    }
  };

  /* ---------------------------------------------------------------- */
  /* reports                                                             */
  /* ---------------------------------------------------------------- */

  var reports = {
    get: function (auditId) {
      return request('/reports/' + encodeURIComponent(auditId)).then(mapReport);
    },

    // AI-enriched report: base report + prioritized recommendations.
    getFull: function (auditId) {
      return Promise.all([
        request('/reports/' + encodeURIComponent(auditId)).then(mapReport),
        request('/ai/' + encodeURIComponent(auditId) + '/priorities')
      ]).then(function (results) {
        var report = results[0];
        var priorities = (results[1] && results[1].priorities) || [];
        report.priorities = priorities.map(function (p) {
          return { title: p.title, description: p.description, severity: p.severity };
        });
        return report;
      });
    },

    share: function (auditId) {
      return request('/reports/' + encodeURIComponent(auditId) + '/share', { method: 'POST' })
        .then(function (data) { return data.share_url; });
    },

    exportPdfBlob: function (auditId) {
      return requestBlob('/reports/' + encodeURIComponent(auditId) + '/export');
    },

    exportEvidenceZipBlob: function (auditId) {
      return requestBlob('/reports/' + encodeURIComponent(auditId) + '/evidence.zip');
    },

    sendToPoc: function (auditId, payload) {
      return request('/reports/' + encodeURIComponent(auditId) + '/send', {
        method: 'POST',
        body: {
          to: payload.to,
          cc: payload.cc,
          subject: payload.subject,
          body: payload.body,
          attachments: payload.attachments
        }
      }).then(mapEmailSendResult);
    },

    getEmailHistory: function (auditId) {
      return request('/reports/' + encodeURIComponent(auditId) + '/email-history')
        .then(function (list) { return list.map(mapEmailHistoryItem); });
    },

    // { pdf: "Audit Report PDF", consent_screenshots: "...", ... } — the
    // same key set emailer.attachments.ATTACHMENT_CHOICES exposes on the
    // backend, so the modal's checkbox list is never a hardcoded copy.
    getAttachmentChoices: function () {
      return request('/reports/email/attachment-choices');
    }
  };

  /* ---------------------------------------------------------------- */
  /* settings                                                            */
  /* ---------------------------------------------------------------- */

  var settings = {
    get: function () {
      return request('/settings/').then(mapSettings);
    },

    save: function (patch) {
      return request('/settings/', { method: 'PATCH', body: settingsPatchToBackend(patch) }).then(mapSettings);
    },

    regenerateApiKey: function () {
      return request('/settings/api-key/regenerate', { method: 'POST' }).then(function (data) { return data.api_key; });
    },

    exportJson: function () {
      return request('/settings/export').then(function (data) {
        return {
          exportedAt: data.exported_at,
          settings: mapSettings(data.settings),
          audits: (data.audits || []).map(mapAudit)
        };
      });
    }
  };

  /* ---------------------------------------------------------------- */
  /* scheduler — recurring per-site audit schedules                     */
  /* ---------------------------------------------------------------- */

  var scheduler = {
    list: function () {
      return request('/scheduler/').then(function (list) { return list.map(mapSchedule); });
    },

    create: function (config) {
      var body = {
        url: config.url,
        frequency: config.frequency,
        time_label: config.timeLabel,
        depth: config.depth || 'homepage',
        modules: config.modules || []
      };
      return request('/scheduler/', { method: 'POST', body: body }).then(mapSchedule);
    },

    update: function (scheduleId, patch) {
      var map = { frequency: 'frequency', timeLabel: 'time_label', depth: 'depth', modules: 'modules', isActive: 'is_active' };
      var body = {};
      Object.keys(patch).forEach(function (key) {
        if (map[key] && patch[key] !== undefined) body[map[key]] = patch[key];
      });
      return request('/scheduler/' + encodeURIComponent(scheduleId), { method: 'PATCH', body: body }).then(mapSchedule);
    },

    remove: function (scheduleId) {
      return request('/scheduler/' + encodeURIComponent(scheduleId), { method: 'DELETE' });
    },

    runNow: function (scheduleId) {
      return request('/scheduler/' + encodeURIComponent(scheduleId) + '/run-now', { method: 'POST' }).then(mapAudit);
    }
  };

  return {
    auth: auth,
    audits: audits,
    reports: reports,
    settings: settings,
    scheduler: scheduler
  };
})();
