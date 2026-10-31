/*
 * Report page: loads ?id=<auditId> and renders the banner, scores, issues,
 * module details, screenshots and the share / print / PDF actions.
 * The "Send to POC" dialog is in email-composer.js.
 */

(function () {
  var U = window.Utils;

  var PASS_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4L19 7"/></svg>';
  var FAIL_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>';
  var WARN_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>';

  // Fixed-size status icon (an unsized SVG grows to fill its container).
  function statusIcon(kind) {
    var svg = kind === 'pass' ? PASS_ICON : (kind === 'warn' ? WARN_ICON : FAIL_ICON);
    return '<span class="status-icon status-icon--' + kind + '" aria-hidden="true">' + svg + '</span>';
  }

  // Section ids that modules can link to; others still show in the score grid.
  var MODULE_CHECK_GRID_IDS = {};
  // Keep in sync with backend GDPR_CHECK_ORDER. severity/failReason are display-only (the "Why?" text).
  var GDPR_CHECK_ITEMS = [
    { key: 'consent_banner', label: 'Consent banner', severity: 'critical',
      failReason: 'No consent banner or CMP was detected' },
    { key: 'accept_control', label: 'Accept control', severity: 'warning',
      failReason: 'No recognizable accept control was found' },
    { key: 'reject_control', label: 'Reject control', severity: 'critical',
      failReason: 'No recognizable reject control was found' },
    { key: 'reject_parity', label: 'Reject parity', severity: 'critical',
      failReason: 'Accept and reject aren\u2019t offered on equal footing (a dark pattern)' },
    { key: 'trackers_blocked_pre_consent', label: 'Non-essential trackers blocked before consent', severity: 'critical',
      failReason: 'Non-essential trackers were detected before consent' },
    { key: 'cookies_blocked_pre_consent', label: 'Non-essential cookies blocked before consent', severity: 'critical',
      failReason: 'Non-essential cookies were detected before consent' },
    { key: 'consent_is_granular', label: 'Consent is granular', severity: 'warning',
      failReason: 'No manage/customize option was found alongside accept/reject' },
    { key: 'privacy_policy_available', label: 'Privacy policy available', severity: 'warning',
      failReason: 'Privacy policy was not detected' },
    { key: 'consent_withdrawal_available', label: 'Consent withdrawal available', severity: 'warning',
      failReason: 'No persistent way to withdraw consent later was found' },
    // Not required: it needs the live browser check (same as the backend).
    { key: 'reject_blocks_tracking', label: 'Reject actually blocks tracking', severity: 'critical',
      failReason: 'Reject does not actually stop tracking', required: false }
  ];

  // Keep in sync with backend CCPA_CHECK_ORDER.
  var CCPA_CHECK_ITEMS = [
    { key: 'privacy_policy_available', label: 'Privacy policy available', severity: 'warning',
      failReason: 'Privacy policy was not detected' },
    { key: 'privacy_choices_link', label: '"Your Privacy Choices" link present', severity: 'warning',
      failReason: 'No "Your Privacy Choices" / California privacy rights link was found' },
    { key: 'do_not_sell_link', label: '"Do Not Sell or Share My Information" link present', severity: 'critical',
      failReason: 'No "Do Not Sell or Share My Information" link was found' },
    { key: 'opt_out_mechanism', label: 'Opt-out mechanism reachable', severity: 'critical',
      failReason: 'No persistent, reachable opt-out mechanism was found' },
    { key: 'gpc_honored', label: 'Global Privacy Control (GPC) signal handling detected', severity: 'warning',
      failReason: 'Global Privacy Control (GPC) signal doesn\u2019t appear to be honored' },
    // Not required: it needs the live browser check.
    { key: 'opt_out_behavior_verified', label: 'Opt-out actually stops tracking', severity: 'critical',
      failReason: 'Opt-out does not actually stop tracking', required: false }
  ];

  var MODULE_SCORE_CHIP_IDS = {};

  // Module names and status words (same as the backend and PDF).
  var MODULE_LABELS = {
    performance: 'Performance', accessibility: 'Accessibility',
    security: 'Security', ux: 'UX', images: 'Images', links: 'Links',
    mobile: 'Mobile', forms: 'Forms', consent: 'Consent', analytics: 'Analytics', journey: 'Journey Map', ai: 'AI Review'
  };
  var OVERALL_STATUS_LABELS = { good: 'Healthy', mid: 'Needs attention', bad: 'Issues found' };

  /* Report helpers */
  // Computed from the same findings and scores as the PDF, so the numbers match.

  function severityCounts(findings) {
    var counts = { critical: 0, warning: 0, info: 0 };
    (findings || []).forEach(function (f) {
      var sev = f.severity || 'info';
      counts[sev] = (counts[sev] || 0) + 1;
    });
    return counts;
  }

  function weakestModule(scoreGrid) {
    if (!scoreGrid || !scoreGrid.length) return null;
    return scoreGrid.reduce(function (worst, cell) {
      return (!worst || cell.score < worst.score) ? cell : worst;
    }, null);
  }

  function overallStatusLabel(score) {
    return OVERALL_STATUS_LABELS[U.scoreBand(score)] || '';
  }

  function moduleLabel(module) {
    return MODULE_LABELS[module] || (module ? module.replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); }) : 'General');
  }

  // Groups findings with the same title and module, with a count.
  function groupByTitleModule(items) {
    var order = [];
    var byKey = {};
    (items || []).forEach(function (item) {
      var key = (item.title || '') + '\u0000' + (item.module || '');
      if (!byKey[key]) {
        byKey[key] = { title: item.title || '', module: item.module || '', description: item.description || '',
          finding_id: item.finding_id || '', severity: item.severity || 'info', step: item.step || '', count: 0,
          review: item.review || null, originalSeverity: item.originalSeverity || item.original_severity || null };
        order.push(key);
      }
      byKey[key].count += 1;
    });
    return order.map(function (key) { return byKey[key]; });
  }

  function findingIdBadge(id) {
    return id ? '<span class="finding-id-badge">' + U.escapeHtml(id) + '</span> ' : '';
  }

  /* Module details: opens the right section when a score card is clicked, and opens all of them for printing. */

  /* Module details as tabs; the <details> elements stay so links keep working. */
  var currentModuleTab = null;

  function selectModuleTab(id, scroll) {
    var group = document.getElementById('moduleDetails');
    var target = id && document.getElementById(id);
    if (!group || !target || target.parentElement !== group) return null;
    currentModuleTab = id;
    U.qsa('.module-accordion', group).forEach(function (d) { d.open = (d.id === id); });
    U.qsa('#moduleTabs .rp-tab').forEach(function (t) {
      var on = t.dataset.tab === id;
      t.setAttribute('aria-selected', String(on));
      t.classList.toggle('is-active', on);
    });
    if (scroll) {
      var sec = document.getElementById('details');
      if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    return target;
  }

  function openModuleAccordion(id) {
    var el = id && document.getElementById(id);
    if (!el) return el;
    if (selectModuleTab(id, false)) return el;
    if (el.tagName === 'DETAILS' && !el.open) el.open = true;
    return el;
  }

  function wireModuleTabs() {
    U.qsa('#moduleTabs .rp-tab').forEach(function (tab) {
      U.on(tab, 'click', function () { selectModuleTab(tab.dataset.tab, false); });
      U.on(tab, 'keydown', function (e) {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        var tabs = U.qsa('#moduleTabs .rp-tab');
        var i = tabs.indexOf(tab) + (e.key === 'ArrowRight' ? 1 : -1);
        var next = tabs[(i + tabs.length) % tabs.length];
        selectModuleTab(next.dataset.tab, false);
        next.focus();
      });
    });
  }

  function wireModuleAccordions() {
    // Also open the Analytics sub-sections for printing.
    var accordions = U.qsa('.module-accordion, .analytics-subsection');
    if (!accordions.length) return;

    // Open the target section when a sidebar link is clicked.
    U.qsa('a[href^="#"]').forEach(function (link) {
      var id = link.getAttribute('href').slice(1);
      if (document.getElementById(id)) U.on(link, 'click', function () { openModuleAccordion(id); });
    });

    // Deep links, e.g. report.html?id=123#consent
    if (location.hash) openModuleAccordion(location.hash.slice(1));
    U.on(window, 'hashchange', function () { openModuleAccordion(location.hash.slice(1)); });

    // Open everything before printing; restore afterwards.
    var reopenIds = [];
    U.on(window, 'beforeprint', function () {
      reopenIds = [];
      accordions.forEach(function (details) {
        if (!details.open) { reopenIds.push(details.id); details.open = true; }
      });
    });
    U.on(window, 'afterprint', function () {
      reopenIds.forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.open = false;
      });
      reopenIds = [];
      if (currentModuleTab) selectModuleTab(currentModuleTab, false);
    });
  }

  // Colours a module's score chip and status icon by score band.
  function setModuleStatus(chipId, iconId, score) {
    var chip = document.getElementById(chipId);
    var icon = document.getElementById(iconId);
    if (score == null) return;
    var band = U.scoreBand(score);
    if (chip) chip.className = 'score-chip score-chip--' + band;
    if (icon) {
      icon.className = 'module-accordion__status module-accordion__status--' + band;
      icon.innerHTML = band === 'good' ? PASS_ICON : (band === 'mid' ? WARN_ICON : FAIL_ICON);
    }
  }


  /* window.EmailComposer used to be defined here, at the top level of this
     file, so email-reports.html could load report.js purely to reuse it.
     It now lives in its own module, assets/js/email-composer.js, which both
     report.html and email-reports.html load directly — see that file's
     header for why. Keeping two copies in sync was the actual bug behind
     the "composer unavailable on Email Reports" issue, so this is the only
     copy now. */

  document.addEventListener('DOMContentLoaded', function () {
    var scoreGrid = document.getElementById('scoreGrid');
    if (!scoreGrid) return; // not on report.html

    var auditId = U.getQueryParam('id');
    var shareBtn = document.getElementById('shareReportBtn');
    var printBtn = document.getElementById('printReportBtn');
    var downloadBtn = document.getElementById('downloadPdfBtn');
    var evidenceBtn = document.getElementById('downloadEvidenceBtn');
    var sendToPocBtn = document.getElementById('sendToPocBtn');
    var emailComposeBtn = document.getElementById('emailComposeBtn');

    // Add ?id= to sidebar links to report.html so they stay on this audit.
    if (auditId) {
      U.qsa('.sidebar__link').forEach(function (link) {
        var raw = link.getAttribute('href') || '';
        if (raw.indexOf('report.html') !== 0 || raw.indexOf('?') !== -1) return;
        var hashAt = raw.indexOf('#');
        var base = hashAt === -1 ? raw : raw.slice(0, hashAt);
        var hash = hashAt === -1 ? '' : raw.slice(hashAt);
        link.setAttribute('href', base + '?id=' + encodeURIComponent(auditId) + hash);
      });
    }

    // Screenshots that no longer exist on the server get a clear placeholder instead of a broken image.
    var missingShots = 0;
    document.addEventListener('error', function (e) {
      var img = e.target;
      if (!img || img.tagName !== 'IMG' || img.dataset.apMissing || !img.closest('.content')) return;
      img.dataset.apMissing = '1';
      missingShots += 1;
      var ph = document.createElement('span');
      ph.className = 'rp-noshot';
      ph.title = 'This screenshot is no longer stored on the server. Re-run the audit to capture it again.';
      ph.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 17-5-5-9 7"/><path d="M3 3l18 18"/></svg>' +
        '<span>Screenshot not available</span>';
      img.replaceWith(ph);
      var link = ph.closest('a');
      if (link) { link.removeAttribute('href'); link.classList.add('is-missing'); }
      var dl = ph.parentElement && ph.parentElement.parentElement &&
        ph.parentElement.parentElement.querySelector('a[download]');
      if (dl && dl !== link) dl.style.display = 'none';
      if (missingShots === 1) {
        var group = document.getElementById('moduleDetails');
        if (group && !document.getElementById('missingShotsNote')) {
          var note = document.createElement('div');
          note.id = 'missingShotsNote';
          note.className = 'rp-note';
          note.textContent = 'Some evidence screenshots for this audit are no longer stored on the server (they are cleared when the server is redeployed). Re-run the audit to capture them again.';
          group.parentNode.insertBefore(note, group);
        }
      }
    }, true);

    // Set up before the auditId check so it works without a report.
    wireModuleTabs();
    wireModuleAccordions();

    if (!auditId) {
      // Opened without an id (e.g. from the sidebar): show the latest completed audit.
      window.Api.audits.getRecent().then(function (list) {
        var done = (list || []).filter(function (a) { return a.status === 'completed'; })[0];
        if (done) {
          window.location.replace('report.html?id=' + encodeURIComponent(done.id) + (window.location.hash || ''));
        } else {
          window.Notifications.error('No report yet', 'Run an audit first. Its report (and Cookie Scanner) will open here.');
        }
      }).catch(function () {
        window.Notifications.error('No report selected', 'Open a report from your dashboard or history so we know which audit to show.');
      });
      return;
    }

    var currentReport = null; // set once the report loads

    // Load email history early, so a render error elsewhere can't leave it empty.
    loadEmailHistory();

    /* Banner actions */

    U.on(shareBtn, 'click', function () {
      window.Api.reports.share(auditId).then(function (shareUrl) {
        var fullUrl = window.APP_CONFIG.API_ORIGIN + shareUrl;
        return U.copyToClipboard(fullUrl);
      }).then(function () {
        window.Notifications.success('Link copied', 'Report link copied to your clipboard.');
      }).catch(function (err) {
        window.Notifications.error('Couldn\'t create share link', err.message || 'Please try again.');
      });
    });

    U.on(printBtn, 'click', function () {
      window.print();
    });

    U.on(downloadBtn, 'click', function () {
      window.Loader.setButtonLoading(downloadBtn, true, 'Preparing PDF…');
      window.Api.reports.exportPdfBlob(auditId).then(function (blob) {
        var host = currentReport ? U.hostnameOf(currentReport.url) : 'report';
        U.downloadBlob('audit-' + host + '-' + auditId + '.pdf', blob);
      }).catch(function (err) {
        window.Notifications.error('Download failed', err.message || 'Could not generate the PDF export.');
      }).finally(function () {
        window.Loader.setButtonLoading(downloadBtn, false);
      });
    });

    U.on(evidenceBtn, 'click', function () {
      window.Loader.setButtonLoading(evidenceBtn, true, 'Packaging evidence…');
      window.Api.reports.exportEvidenceZipBlob(auditId).then(function (blob) {
        var host = currentReport ? U.hostnameOf(currentReport.url) : 'report';
        U.downloadBlob('audit-' + host + '-' + auditId + '-evidence.zip', blob);
      }).catch(function (err) {
        window.Notifications.error('Download failed', err.message || 'Could not build the evidence package.');
      }).finally(function () {
        window.Loader.setButtonLoading(evidenceBtn, false);
      });
    });

    // Both "Send to POC" buttons open the shared composer, each returning focus to itself.
    function openEmailComposer(trigger) {
      window.EmailComposer.open({
        auditId: auditId,
        report: currentReport,
        trigger: trigger,
        onSent: loadEmailHistory
      });
    }

    U.on(sendToPocBtn, 'click', function () {
      closeMoreMenu();
      openEmailComposer(sendToPocBtn);
    });

    U.on(emailComposeBtn, 'click', function () {
      openEmailComposer(emailComposeBtn);
    });

    /* "More" menu: Print / Evidence ZIP / Send to POC */
    var moreDropdown = document.getElementById('reportMoreDropdown');
    var moreBtn = document.getElementById('reportMoreBtn');

    function closeMoreMenu() {
      if (!moreDropdown) return;
      moreDropdown.classList.remove('is-open');
      if (moreBtn) moreBtn.setAttribute('aria-expanded', 'false');
    }

    U.on(moreBtn, 'click', function (e) {
      e.stopPropagation();
      if (!moreDropdown) return;
      var willOpen = !moreDropdown.classList.contains('is-open');
      moreDropdown.classList.toggle('is-open', willOpen);
      moreBtn.setAttribute('aria-expanded', String(willOpen));
    });

    // Close the menu after an action.
    U.on(printBtn, 'click', closeMoreMenu);
    U.on(evidenceBtn, 'click', closeMoreMenu);

    U.on(document, 'click', function (e) {
      if (moreDropdown && !moreDropdown.contains(e.target)) closeMoreMenu();
    });
    U.on(document, 'keydown', function (e) {
      if (e.key === 'Escape') closeMoreMenu();
    });

    /* Ask AI: questions about this audit; earlier turns are sent for context. */
    (function initAskAi() {
      var form = document.getElementById('chatForm');
      var input = document.getElementById('chatInput');
      var sendBtn = document.getElementById('chatSendBtn');
      var messages = document.getElementById('chatMessages');
      if (!form || !input || !messages) return;

      var chatHistory = [];

      function appendMessage(text, variant) {
        var el = document.createElement('div');
        el.className = 'chat-msg chat-msg--' + variant;
        el.textContent = text;
        messages.appendChild(el);
        messages.scrollTop = messages.scrollHeight;
        return el;
      }

      function appendPending() {
        var el = document.createElement('div');
        el.className = 'chat-msg chat-msg--pending';
        el.innerHTML = '<span class="ai-panel__dot"></span><span class="ai-panel__dot"></span><span class="ai-panel__dot"></span>';
        messages.appendChild(el);
        messages.scrollTop = messages.scrollHeight;
        return el;
      }

      U.on(form, 'submit', function (e) {
        e.preventDefault();
        var question = input.value.trim();
        if (!question) return;

        appendMessage(question, 'user');
        input.value = '';
        input.disabled = true;
        window.Loader.setButtonLoading(sendBtn, true, 'Asking…');

        var pendingEl = appendPending();

        window.Api.ai.chat(auditId, question, chatHistory).then(function (answer) {
          pendingEl.remove();
          appendMessage(answer, 'assistant');
          chatHistory.push({ question: question, answer: answer });
        }).catch(function (err) {
          pendingEl.remove();
          appendMessage(err.message || 'Something went wrong answering that. Please try again.', 'error');
        }).finally(function () {
          input.disabled = false;
          window.Loader.setButtonLoading(sendBtn, false);
          input.focus();
        });
      });
    })();

    /* Load and render */

    Promise.all([
      window.Api.reports.getFull(auditId).catch(function () {
        // If the AI version fails, use the plain report.
        return window.Api.reports.get(auditId);
      }),
      window.Api.audits.getConsent(auditId).catch(function () { return null; }),
      window.Api.audits.getAnalytics(auditId).catch(function () { return null; }),
      window.Api.audits.getJourney(auditId).catch(function () { return null; }),
      window.Api.audits.getCookies ? window.Api.audits.getCookies(auditId).catch(function () { return null; }) : null
    ]).then(function (results) {
      currentReport = results[0];
      var allFindings = currentReport.findings || [];
      currentReport.acceptedFindings = allFindings.filter(function (f) { return f.review && f.review.status === 'accepted'; });
      currentReport.findings = allFindings.filter(function (f) { return !(f.review && f.review.status === 'accepted'); });
      renderBanner(currentReport);
      renderGlance(currentReport);
      renderIssues(currentReport);
      if (!currentModuleTab) {
        var scored = (currentReport.scoreGrid || []).filter(function (c) { return DETAIL_TABS.indexOf(c.module) !== -1; });
        var weakest = weakestModule(scored);
        selectModuleTab(weakest ? weakest.module : 'consent', false);
      }
      renderModuleSections(currentReport);
      renderConsent(results[1]);
      renderAnalytics(results[2]);
      renderJourney(results[3]);
      renderCookies(results[4]);
      showTabsForModulesRun({ consent: results[1], analytics: results[2], journey: results[3],
                              // Cookies tab: shown whenever Consent or Journey ran.
                              cookies: (results[1] || results[3]) ? (results[4] || { available: false }) : null });
      document.title = 'Audit Report — ' + U.hostnameOf(currentReport.url) + ' — AuditPulse';
    }).catch(function (err) {
      window.Notifications.error('Couldn\'t load report', err.message || 'This report may not exist or may still be running.');
    });

    /* Renderers */

    /* Show only tabs for modules that ran (a module can run without a score). */
    function showTabsForModulesRun(moduleResults) {
      var ran = DETAIL_TABS.filter(function (m) {
        return !!moduleResults[m] || (currentReport.scoreGrid || []).some(function (c) { return c.module === m; });
      });
      if (!ran.length) {
        // No module ran (e.g. the site blocked the audit).
        var sec = document.getElementById('details');
        if (sec) sec.hidden = true;
        return;
      }
      DETAIL_TABS.forEach(function (m) {
        var tab = document.querySelector('.rp-tab[data-tab="' + m + '"]');
        if (tab) tab.hidden = ran.indexOf(m) === -1;
      });
      var current = document.querySelector('.rp-tab[aria-selected="true"]');
      if (!current || current.hidden) selectModuleTab(ran[0], false);
    }

    function renderJourney(journey) {
      var chipEl = document.getElementById('journeyScoreChip');
      if (!window.JourneyRender) return;
      var view = window.JourneyRender.renderReport(journey, {
        content: 'journeyContent', empty: 'journeyEmpty', overview: 'journeyOverview', health: 'journeyHealth', summary: 'journeySummary',
        map: 'journeyMap', detail: 'journeyDetail', coverage: 'journeyCoverage', forms: 'journeyForms',
        interactions: 'journeyInteractions', clickDetail: 'journeyClickDetail', findings: 'journeyFindings',
        pages: 'journeyPages', how: 'journeyHow', gallery: 'journeyGallery', galleryDetail: 'journeyGalleryDetail'
      });
      if (chipEl) {
        if (view && view.score != null) {
          chipEl.textContent = view.score + ' / 100';
          setModuleStatus('journeyScoreChip', 'journeyStatusIcon', view.score);
        } else {
          chipEl.textContent = view ? 'Not scored' : 'Not scanned';
        }
      }
    }

    function renderCookies(inv) {
      if (!window.CookieRender) return;
      window.CookieRender.render(inv, { content: 'cookiesContent', empty: 'cookiesEmpty', chip: 'cookiesCountChip' }, {
        onExport: function (btn) {
          window.Loader.setButtonLoading(btn, true);
          window.Api.audits.exportCookiesCsvBlob(auditId).then(function (blob) {
            var host = U.hostnameOf(currentReport ? currentReport.url : '').replace(/\./g, '-') || 'site';
            U.downloadBlob('cookies-' + host + '-audit-' + auditId + '.csv', blob);
          }).catch(function (err) {
            window.Notifications.error('Couldn\'t export cookies', err.message || 'Please try again.');
          }).finally(function () { window.Loader.setButtonLoading(btn, false); });
        }
      });
      var badge = document.getElementById('tabScore-cookies');
      if (badge) {
        var n = inv && inv.available ? (inv.summary || {}).total : null;
        badge.textContent = n == null ? '–' : n;
        var issues = inv && inv.available ? (inv.summary || {}).with_issues : 0;
        badge.setAttribute('data-band', issues ? 'bad' : 'good');
        badge.title = n == null ? '' : n + ' cookies, ' + issues + ' with issues';
      }
    }

    function renderBanner(report) {
      var host = U.hostnameOf(report.url);
      var favicon = document.getElementById('bannerFavicon');
      var urlEl = document.getElementById('bannerUrl');
      var metaEl = document.getElementById('bannerMeta');
      var ring = document.getElementById('bannerScoreRing');
      var circle = document.getElementById('bannerScoreCircle');
      var label = document.getElementById('bannerScoreLabel');
      var bandEl = document.getElementById('bannerScoreBand');

      if (favicon) favicon.textContent = U.faviconLetter(report.url);
      if (urlEl) urlEl.textContent = host;
      if (metaEl) {
        metaEl.textContent = 'Completed ' + U.formatRelativeTime(new Date(report.generatedAt).getTime());
        var nAcc = groupByTitleModule(report.acceptedFindings || []).length;
        if (nAcc && report.rawOverall != null) {
          metaEl.textContent += ' · Score leaves out ' + nAcc + ' accepted finding' + (nAcc === 1 ? '' : 's') +
            ' (measured: ' + report.rawOverall + '/100)';
        }
      }
      // Nothing scored: show "Not scored", never 0.
      if (!(report.scoreGrid || []).length) {
        if (label) label.textContent = '–';
        if (circle) U.setRingProgress(circle, 0);
        if (bandEl) { bandEl.textContent = 'Not scored'; bandEl.removeAttribute('data-band'); }
        return;
      }
      if (label) label.textContent = report.overall;
      if (ring) U.setRingBand(ring, report.overall);
      if (circle) U.setRingProgress(circle, report.overall);
      if (bandEl) {
        bandEl.textContent = overallStatusLabel(report.overall);
        if (ring) ring.title = report.overall + ' out of 100 · ' + overallStatusLabel(report.overall);
        bandEl.setAttribute('data-band', U.scoreBand(report.overall));
      }
    }

    /* At a glance: summary, a card per module, severity counts. */

    var SEV_ORDER = { critical: 0, warning: 1, info: 2 };
    var SEV_LABEL = { critical: 'Critical', warning: 'Warning', info: 'Info' };
    var DETAIL_TABS = ['consent', 'analytics', 'journey', 'cookies'];

    // Same words as the overall band, the PDF and the dashboard.
    function bandWord(score) {
      var band = U.scoreBand(score);
      return band === 'good' ? 'Healthy' : (band === 'mid' ? 'Needs attention' : 'Issues found');
    }

    function renderGlance(report) {
      if (window.ScoreHelp) window.ScoreHelp.setContext(report.scoreGrid || [], report.overall);
      var summaryEl = document.getElementById('execSummaryText');
      if (summaryEl) {
        var text = typeof report.executiveSummary === 'string' ? report.executiveSummary.trim() : '';
        summaryEl.textContent = text;
        summaryEl.hidden = !text;
      }

      var findings = report.findings || [];
      var issuesByModule = {};
      groupByTitleModule(findings).forEach(function (g) {
        if (g.severity === 'info') return;
        issuesByModule[g.module] = (issuesByModule[g.module] || 0) + 1;
      });

      if (scoreGrid) {
        var cells = (report.scoreGrid || []).slice().sort(function (a, b) {
          var ia = DETAIL_TABS.indexOf(a.module), ib = DETAIL_TABS.indexOf(b.module);
          return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
        });
        scoreGrid.innerHTML = cells.map(function (cell) {
          var band = U.scoreBand(cell.score);
          var n = issuesByModule[cell.module] || 0;
          var sub = (n ? n + (n === 1 ? ' issue' : ' issues') : 'No issues') + ' · ' + bandWord(cell.score);
          var clickable = DETAIL_TABS.indexOf(cell.module) !== -1;
          return '<' + (clickable ? 'button type="button"' : 'div') + ' class="rp-mod" data-band="' + band + '"' +
              (clickable ? ' data-module="' + U.escapeHtml(cell.module) + '" title="Open ' + U.escapeHtml(cell.label) + ' details"' : '') + '>' +
            '<span class="rp-mod__score" title="' + cell.score + ' out of 100 · ' + bandWord(cell.score) + '">' + cell.score + '<small>/100</small></span>' +
            '<span class="rp-mod__text"><span class="rp-mod__label">' + U.escapeHtml(cell.label) + '</span>' +
              '<span class="rp-mod__sub">' + U.escapeHtml(sub) + '</span></span>' +
            '<span class="rp-mod__bar" aria-hidden="true"><i style="width:' + Math.max(0, Math.min(100, cell.score)) + '%"></i></span>' +
          '</' + (clickable ? 'button' : 'div') + '>';
        }).join('') || '<p class="rp-muted">Not scored: no module produced a score in this run. Open the module details below to see why.</p>';
        U.qsa('.rp-mod[data-module]', scoreGrid).forEach(function (btn) {
          U.on(btn, 'click', function () { selectModuleTab(btn.dataset.module, true); });
        });
      }

      // Score badges on the module tabs.
      (report.scoreGrid || []).forEach(function (cell) {
        var el = document.getElementById('tabScore-' + cell.module);
        if (el) {
          el.textContent = cell.score;
          el.setAttribute('data-band', U.scoreBand(cell.score));
          el.title = cell.score + ' out of 100 · ' + bandWord(cell.score);
        }
      });

      // Only show tabs for modules this audit ran.
      var ran = (report.scoreGrid || []).map(function (c) { return c.module; })
        .filter(function (m) { return DETAIL_TABS.indexOf(m) !== -1; });
      if (ran.length) {
        DETAIL_TABS.forEach(function (m) {
          var tab = document.querySelector('.rp-tab[data-tab="' + m + '"]');
          if (tab) tab.hidden = ran.indexOf(m) === -1;
        });
        var current = document.querySelector('.rp-tab[aria-selected="true"]');
        if (!current || current.hidden) selectModuleTab(ran[0], false);
      }

      var counts = severityCounts(findings);
      var sevEl = document.getElementById('severityTable');
      if (sevEl) {
        sevEl.innerHTML = ['critical', 'warning', 'info'].map(function (sev) {
          return '<button type="button" class="rp-count rp-count--' + sev + '" data-sev="' + sev + '">' +
            '<span class="rp-count__num">' + (counts[sev] || 0) + '</span>' +
            '<span class="rp-count__label">' + (sev === 'warning' && counts[sev] !== 1 ? 'Warnings' : SEV_LABEL[sev]) + '</span>' +
          '</button>';
        }).join('');
        U.qsa('.rp-count', sevEl).forEach(function (btn) {
          U.on(btn, 'click', function () {
            issueState.sev = btn.dataset.sev;
            issueState.expandAll = false;
            renderIssueList();
            var sec = document.getElementById('issues');
            if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
          });
        });
      }
    }

    /*
     * Issues to fix: every finding once (grouped), worst first. Each row opens to
     * what was found, why it matters, how to fix it, and a link to the evidence.
     */

    var ISSUES_INITIAL = 10;
    var issueState = { sev: 'all', module: 'all', q: '', expandAll: false, items: [] };

    function buildIssues(report) {
      var steps = {};
      var plan = report.actionPlan || {};
      ['quickWins', 'shortTerm', 'longTerm'].forEach(function (k) {
        (plan[k] || []).forEach(function (s) {
          var key = (s.title || '') + '\u0000' + (s.module || '');
          if (s.step && !steps[key]) steps[key] = s.step;
          if (s.step && !steps['\u0000' + s.title]) steps['\u0000' + s.title] = s.step;
        });
      });
      var impact = {};
      (report.businessImpact || []).forEach(function (b) {
        if (b.title && b.impact && !impact[b.title]) impact[b.title] = b.impact;
      });
      var rank = {};
      (report.priorities || []).forEach(function (p, i) { if (p.title && !(p.title in rank)) rank[p.title] = i; });

      var recos = {};
      (report.findings || []).forEach(function (f) {
        var key = (f.title || '') + '\u0000' + (f.module || '');
        if (f.recommendation && !recos[key]) recos[key] = f.recommendation;
      });

      var items = groupByTitleModule(report.findings || []).map(function (g) {
        var key = g.title + '\u0000' + g.module;
        return {
          title: g.title, module: g.module, severity: SEV_ORDER[g.severity] != null ? g.severity : 'info',
          description: g.description, count: g.count, findingId: g.finding_id,
          review: g.review, originalSeverity: g.originalSeverity,
          fix: recos[key] || steps[key] || steps['\u0000' + g.title] || '',
          impact: impact[g.title] || '',
          rank: (g.title in rank) ? rank[g.title] : 999
        };
      });
      items.sort(function (a, b) {
        return (SEV_ORDER[a.severity] - SEV_ORDER[b.severity]) || (a.rank - b.rank) || (b.count - a.count);
      });
      return items;
    }

    function issueMatches(it) {
      if (issueState.sev !== 'all' && it.severity !== issueState.sev) return false;
      if (issueState.module !== 'all' && it.module !== issueState.module) return false;
      if (issueState.q) {
        var hay = (it.title + ' ' + it.description + ' ' + moduleLabel(it.module)).toLowerCase();
        if (hay.indexOf(issueState.q) === -1) return false;
      }
      return true;
    }

    var CHEVRON = '<svg class="rp-issue__chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';

    function issueRowHtml(it, idx) {
      var meta = [];
      if (it.rank < 5 && it.severity !== 'info') meta.push('<span class="rp-tag rp-tag--first">Fix first</span>');
      meta.push('<span class="rp-issue__module">' + U.escapeHtml(moduleLabel(it.module)) + '</span>');
      if (it.count > 1) meta.push('<span class="rp-issue__count">' + it.count + '×</span>');
      var bodyId = 'issueBody' + idx;
      var rows = '';
      if (it.description) rows += '<div class="rp-kv"><dt>What we found</dt><dd>' + U.escapeHtml(it.description) + '</dd></div>';
      if (it.impact) rows += '<div class="rp-kv"><dt>Why it matters</dt><dd>' + U.escapeHtml(it.impact) + '</dd></div>';
      if (it.fix) rows += '<div class="rp-kv rp-kv--fix"><dt>How to fix</dt><dd>' + U.escapeHtml(it.fix) + '</dd></div>';
      var link = DETAIL_TABS.indexOf(it.module) !== -1
        ? '<button type="button" class="rp-link" data-goto="' + U.escapeHtml(it.module) + '">See evidence in ' + U.escapeHtml(moduleLabel(it.module)) + ' →</button>'
        : '';
      var verify = it.review && it.review.status === 'to_verify';
      if (verify) {
        rows += '<div class="rp-kv"><dt>Marked “To be verified”</dt><dd>' +
          U.escapeHtml(it.review.note || 'No reason given.') + reviewByline(it.review) +
          (it.originalSeverity ? ' Measured as ' + U.escapeHtml(SEV_LABEL[it.originalSeverity] || it.originalSeverity) + '.' : '') + '</dd></div>';
      }
      var actions = '<div class="rp-review" data-title="' + U.escapeHtml(it.title) + '" data-module="' + U.escapeHtml(it.module) + '">' +
        '<button type="button" class="btn btn--sm btn--secondary" data-review="accepted">Mark as intentional / accepted</button>' +
        (verify ? '<button type="button" class="btn btn--sm btn--ghost" data-review="none">Remove “To be verified”</button>'
                : '<button type="button" class="btn btn--sm btn--ghost" data-review="to_verify">Mark “To be verified”</button>') +
      '</div>';
      return '<div class="rp-issue rp-issue--' + it.severity + '" role="listitem">' +
        '<button type="button" class="rp-issue__row" aria-expanded="false" aria-controls="' + bodyId + '">' +
          (verify ? '<span class="rp-sev rp-sev--verify">To be verified</span>'
                  : '<span class="rp-sev rp-sev--' + it.severity + '">' + SEV_LABEL[it.severity] + '</span>') +
          '<span class="rp-issue__title">' + findingIdBadge(it.findingId) + U.escapeHtml(it.title) + '</span>' +
          '<span class="rp-issue__meta">' + meta.join('') + '</span>' +
          CHEVRON +
        '</button>' +
        '<div class="rp-issue__body" id="' + bodyId + '" hidden><dl>' + rows + '</dl>' + link + actions + '</div>' +
      '</div>';
    }

    function reviewByline(review) {
      if (!review) return '';
      var parts = [];
      if (review.by) parts.push(review.by);
      if (review.at) parts.push(new Date(review.at).toLocaleDateString());
      return parts.length ? ' <span class="rp-muted">(' + U.escapeHtml(parts.join(', ')) + ')</span>' : '';
    }

    // Findings the site's team marked as intentional / accepted: listed apart, out of the score and priorities.
    function renderAcceptedPanel() {
      var list = document.getElementById('issueList');
      if (!list) return;
      var panel = document.getElementById('acceptedPanel');
      if (!panel) {
        panel = document.createElement('details');
        panel.id = 'acceptedPanel';
        panel.className = 'rp-accepted';
        var more = document.getElementById('issueShowMore');
        (more || list).insertAdjacentElement('afterend', panel);
      }
      var groups = groupByTitleModule((currentReport && currentReport.acceptedFindings) || []);
      panel.hidden = !groups.length;
      if (!groups.length) { panel.innerHTML = ''; return; }
      panel.innerHTML = '<summary>Accepted / intentional (' + groups.length + ') — not counted in the score or priorities</summary>' +
        '<div class="rp-accepted__list">' + groups.map(function (g) {
          return '<div class="rp-accepted__item">' +
            '<div><span class="rp-sev rp-sev--accepted">Accepted</span> <strong>' + U.escapeHtml(g.title) + '</strong>' +
              ' <span class="rp-issue__module">' + U.escapeHtml(moduleLabel(g.module)) + '</span></div>' +
            '<p class="rp-muted">' + U.escapeHtml((g.review && g.review.note) || 'No reason given.') + reviewByline(g.review) + '</p>' +
            '<div class="rp-review" data-title="' + U.escapeHtml(g.title) + '" data-module="' + U.escapeHtml(g.module) + '">' +
              '<button type="button" class="btn btn--sm btn--ghost" data-review="none">Undo — count it again</button></div>' +
          '</div>';
        }).join('') + '</div>';
      wireReviewButtons(panel);
    }

    function wireReviewButtons(root) {
      U.qsa('.rp-review [data-review]', root).forEach(function (btn) {
        U.on(btn, 'click', function (ev) {
          ev.stopPropagation();
          var box = btn.closest('.rp-review');
          var status = btn.dataset.review === 'none' ? null : btn.dataset.review;
          if (!status) { saveReview(box, null, '', btn); return; }
          if (box.querySelector('.rp-review__form')) return;
          var form = document.createElement('div');
          form.className = 'rp-review__form';
          form.innerHTML = '<label class="rp-muted" style="display:block;margin:8px 0 4px;">' +
              (status === 'accepted' ? 'Why is this intentional? (e.g. vendor approved by the DPO)' : 'What needs to be verified?') + '</label>' +
            '<textarea rows="2" maxlength="2000" style="width:100%;"></textarea>' +
            '<p class="rp-muted" style="margin:4px 0 8px;">Applies to every audit of this website, including future ones. You can undo it at any time.</p>' +
            '<button type="button" class="btn btn--sm btn--primary" data-save>Save</button> ' +
            '<button type="button" class="btn btn--sm btn--ghost" data-cancel>Cancel</button>';
          box.appendChild(form);
          var ta = form.querySelector('textarea');
          ta.focus();
          U.on(form.querySelector('[data-cancel]'), 'click', function () { form.remove(); });
          U.on(form.querySelector('[data-save]'), 'click', function (e2) { saveReview(box, status, ta.value, e2.currentTarget); });
        });
      });
    }

    function saveReview(box, status, note, btn) {
      if (window.Loader) window.Loader.setButtonLoading(btn, true);
      window.Api.audits.reviewFinding(auditId, {
        module: box.dataset.module, title: box.dataset.title, status: status, note: note || ''
      }).then(function () {
        window.Notifications.success('Saved', status === 'accepted' ? 'Marked as intentional / accepted for this website.'
          : (status === 'to_verify' ? 'Marked “To be verified” for this website.' : 'Mark removed.'));
        setTimeout(function () { window.location.reload(); }, 600);
      }).catch(function (err) {
        if (window.Loader) window.Loader.setButtonLoading(btn, false);
        window.Notifications.error('Couldn\'t save', err.message || 'Please try again.');
      });
    }

    function renderIssueList() {
      var list = document.getElementById('issueList');
      var more = document.getElementById('issueShowMore');
      var sub = document.getElementById('issuesSubhead');
      var segEl = document.getElementById('issueSevFilter');
      if (!list) return;
      var all = issueState.items;

      if (segEl) {
        var counts = { all: all.length, critical: 0, warning: 0, info: 0 };
        all.forEach(function (it) { counts[it.severity] += 1; });
        segEl.innerHTML = ['all', 'critical', 'warning', 'info'].map(function (k) {
          var label = k === 'all' ? 'All' : SEV_LABEL[k];
          return '<button type="button" class="rp-seg__btn" data-sev="' + k + '" aria-pressed="' + (issueState.sev === k) + '">' +
            label + ' <span class="rp-seg__n">' + counts[k] + '</span></button>';
        }).join('');
        U.qsa('.rp-seg__btn', segEl).forEach(function (b) {
          U.on(b, 'click', function () { issueState.sev = b.dataset.sev; issueState.expandAll = false; renderIssueList(); });
        });
      }

      if (sub) {
        var c = all.filter(function (i) { return i.severity === 'critical'; }).length;
        var w = all.filter(function (i) { return i.severity === 'warning'; }).length;
        sub.textContent = all.length
          ? (c ? c + ' critical' : 'No critical issues') + ', ' + w + ' warning' + (w === 1 ? '' : 's') +
            ' — sorted by severity. Click an issue to see the details and how to fix it.'
          : 'No issues were found in this audit.';
      }

      var shown = all.filter(issueMatches);
      if (!all.length) {
        list.innerHTML = '<div class="rp-empty">Nothing to fix — no issues were found in this audit.</div>';
      } else if (!shown.length) {
        list.innerHTML = '<div class="rp-empty">No issues match these filters.</div>';
      } else {
        var limit = issueState.expandAll ? shown.length : ISSUES_INITIAL;
        list.innerHTML = shown.slice(0, limit).map(issueRowHtml).join('');
      }

      if (more) {
        var hiddenCount = shown.length - ISSUES_INITIAL;
        more.hidden = issueState.expandAll || hiddenCount <= 0;
        more.textContent = 'Show all ' + shown.length + ' issues';
      }

      U.qsa('.rp-issue__row', list).forEach(function (row) {
        U.on(row, 'click', function () {
          var body = document.getElementById(row.getAttribute('aria-controls'));
          var open = row.getAttribute('aria-expanded') === 'true';
          row.setAttribute('aria-expanded', String(!open));
          if (body) body.hidden = open;
        });
      });
      U.qsa('.rp-link[data-goto]', list).forEach(function (a) {
        U.on(a, 'click', function () { selectModuleTab(a.dataset.goto, true); });
      });
      wireReviewButtons(list);
      renderAcceptedPanel();
    }

    function renderIssues(report) {
      issueState.items = buildIssues(report);
      var modSel = document.getElementById('issueModuleFilter');
      if (modSel) {
        var mods = [];
        issueState.items.forEach(function (it) { if (mods.indexOf(it.module) === -1) mods.push(it.module); });
        modSel.innerHTML = '<option value="all">All modules</option>' + mods.map(function (m) {
          return '<option value="' + U.escapeHtml(m) + '">' + U.escapeHtml(moduleLabel(m)) + '</option>';
        }).join('');
        modSel.hidden = mods.length < 2;
        U.on(modSel, 'change', function () { issueState.module = modSel.value; issueState.expandAll = false; renderIssueList(); });
      }
      var search = document.getElementById('issueSearch');
      if (search) {
        U.on(search, 'input', function () { issueState.q = search.value.trim().toLowerCase(); renderIssueList(); });
      }
      var more = document.getElementById('issueShowMore');
      if (more) U.on(more, 'click', function () { issueState.expandAll = true; renderIssueList(); });
      // Printing shows every issue, unfiltered.
      U.on(window, 'beforeprint', function () {
        issueState.sev = 'all'; issueState.module = 'all'; issueState.q = ''; issueState.expandAll = true;
        if (search) search.value = '';
        if (modSel) modSel.value = 'all';
        renderIssueList();
      });
      renderIssueList();
    }

    function renderCheckGrid(containerId, findingsForModule) {
      var el = document.getElementById(containerId);
      if (!el) return;
      if (!findingsForModule.length) {
        el.innerHTML = '<div class="check-item check-item--pass"><span class="check-item__icon">' + PASS_ICON + '</span><span class="check-item__label">No issues found</span></div>';
        return;
      }
      el.innerHTML = findingsForModule.map(function (f) {
        var cls = f.severity === 'critical' ? 'check-item--fail' : 'check-item--warn';
        var icon = f.severity === 'critical' ? FAIL_ICON : WARN_ICON;
        return '<div class="check-item ' + cls + '"><span class="check-item__icon">' + icon + '</span><span class="check-item__label">' + findingIdBadge(f.finding_id) + U.escapeHtml(f.title) + '</span></div>';
      }).join('');
    }

    function renderModuleSections(report) {
      var scoreByModule = {};
      report.scoreGrid.forEach(function (c) { scoreByModule[c.module] = c.score; });

      Object.keys(MODULE_SCORE_CHIP_IDS).forEach(function (module) {
        var chip = document.getElementById(MODULE_SCORE_CHIP_IDS[module]);
        var score = scoreByModule[module];
        if (chip && score != null) chip.textContent = score + ' / 100';
        setModuleStatus(MODULE_SCORE_CHIP_IDS[module], module + 'StatusIcon', score);
      });

      Object.keys(MODULE_CHECK_GRID_IDS).forEach(function (module) {
        var findingsForModule = report.findings.filter(function (f) { return f.module === module; });
        renderCheckGrid(MODULE_CHECK_GRID_IDS[module], findingsForModule);
      });
    }

    // API value -> { ok, tested }: true = pass, false = fail, null/missing = not tested (not `!!value`).
    function checkResultFromValue(value) {
      return { ok: value === true, tested: value === true || value === false };
    }

    // Overall GDPR/CCPA result from the required checks:
    // any required check false -> 'fail'; all true -> 'pass'; otherwise 'not_tested'.
    function complianceStatus(checkItems, checksMap) {
      var requiredResults = checkItems
        .filter(function (item) { return item.required !== false; })
        .map(function (item) { return checkResultFromValue(checksMap[item.key]); });

      if (requiredResults.some(function (r) { return r.tested && !r.ok; })) return 'fail';
      if (requiredResults.length && requiredResults.every(function (r) { return r.tested; })) return 'pass';
      return 'not_tested';
    }

    function renderCheckItemRow(item) {
      var tested = item.tested !== false;
      var cls = !tested ? 'check-item--pending' : (item.ok ? 'check-item--pass' : 'check-item--fail');
      var icon = !tested ? '' : (item.ok ? PASS_ICON : FAIL_ICON);
      return '<div class="check-item ' + cls + '"><span class="check-item__icon">' + icon + '</span><span class="check-item__label">' + U.escapeHtml(item.label) + (tested ? '' : ' (not tested)') + '</span></div>';
    }

    // GDPR/CCPA check row; a failed check also shows its reason and the backend's evidence.
    function renderConsentCheckDetailRow(item, failReason, evidence) {
      var tested = item.tested !== false;
      var cls = !tested ? 'check-item--pending' : (item.ok ? 'check-item--pass' : 'check-item--fail');
      var icon = !tested ? '' : (item.ok ? PASS_ICON : FAIL_ICON);
      var html = '<div class="check-item ' + cls + '"><span class="check-item__icon">' + icon + '</span><span class="check-item__label">' + U.escapeHtml(item.label) + (tested ? '' : ' (not tested)') + '</span></div>';

      if (tested && !item.ok && failReason) {
        html += '<div class="check-item__detail" style="margin: 2px 0 10px 34px;">' +
          '<p class="text-sm" style="color: var(--text-tertiary); font-weight: 600; margin: 6px 0 2px;">Reason</p>' +
          '<p class="text-sm" style="margin: 0;">' + U.escapeHtml(failReason) + '</p>';

        if (evidence && evidence.summary) {
          html += '<p class="text-sm" style="color: var(--text-tertiary); font-weight: 600; margin: 8px 0 2px;">Evidence</p>' +
            '<p class="text-sm" style="margin: 0;">' + U.escapeHtml(evidence.summary) + '</p>';
        }

        if (evidence && evidence.items && evidence.items.length) {
          html += '<p class="text-sm" style="color: var(--text-tertiary); font-weight: 600; margin: 8px 0 2px;">' + U.escapeHtml(evidence.items_label || 'Detected') + '</p>' +
            '<ul style="margin: 0; padding: 0; list-style: none;">' +
            evidence.items.map(function (name) {
              return '<li class="text-sm" style="margin-bottom: 2px;">\u2022 ' + U.escapeHtml(name) + '</li>';
            }).join('') +
            '</ul>';
        }

        html += '</div>';
      }
      return html;
    }

    // One GDPR or CCPA section: all checks, then "Why did X fail?" for failed ones. `status` from complianceStatus().
    function renderComplianceSummary(label, status, checkItems, checksMap, evidenceMap) {
      var failed = checkItems.filter(function (c) { return checksMap[c.key] === false; });
      var passed = checkItems.filter(function (c) { return checksMap[c.key] === true; });

      // No inner header: the section title already shows the result.
      var html = '';

      // All checks
      html += '<div style="margin-bottom: 16px;">' +
        '<div class="text-sm" style="color: var(--text-tertiary); font-weight: 600; margin: 0 0 10px; padding: 0 0 6px; border-bottom: 1px solid var(--border, #e5e7eb);">Checks</div>' +
        '<div style="display: grid; gap: 0; padding: 0;">';
      
      checkItems.forEach(function (item) {
        var itemStatus = checkResultFromValue(checksMap[item.key]);
        var itemCls = !itemStatus.tested ? 'check-item--pending' : (itemStatus.ok ? 'check-item--pass' : 'check-item--fail');
        var itemIcon = !itemStatus.tested ? '' : (itemStatus.ok ? PASS_ICON : FAIL_ICON);
        
        html += '<div class="check-item ' + itemCls + '" style="margin-bottom: 2px; padding: 4px 0;">' +
          '<span class="check-item__icon" style="font-size: 0.9em;">' + itemIcon + '</span>' +
          '<span class="check-item__label" style="font-size: 0.9em;">' + U.escapeHtml(item.label) + 
          (itemStatus.tested ? '' : ' (not tested)') +
          // Why it couldn't be tested (backend reason; older audits have none).
          (!itemStatus.tested && evidenceMap && evidenceMap[item.key] && evidenceMap[item.key].reason
            ? '<span style="display: block; font-size: 0.85em; color: var(--text-tertiary);">' +
              U.escapeHtml(evidenceMap[item.key].reason) + '</span>'
            : '') +
          '</span></div>';
      });
      
      html += '</div></div>';

      // Failed checks only
      if (status === 'fail' && failed.length) {
        html += '<div style="background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); padding: 12px; border-left: 3px solid var(--color-fail, #dc2626);">' +
          '<div class="text-sm" style="color: var(--text-primary); font-weight: 600; margin: 0 0 10px;">Why did ' + U.escapeHtml(label) + ' fail?</div>' +
          '<div style="display: grid; gap: 8px;">';
        
        failed.forEach(function (failedItem) {
          var evidence = evidenceMap && evidenceMap[failedItem.key];
          html += '<div class="why-fail__item">' + statusIcon('fail') +
            '<div class="why-fail__body">' +
            '<div class="why-fail__title">' + U.escapeHtml(failedItem.label) + '</div>' +
            '<div class="why-fail__reason">' + U.escapeHtml((evidence && evidence.reason) || failedItem.failReason || failedItem.label) + '</div>';

          if (evidence && evidence.summary) {
            html += '<div class="why-fail__evidence-summary">' + U.escapeHtml(evidence.summary) + '</div>';
          }

          if (evidence && evidence.items && evidence.items.length) {
            html += '<div class="why-fail__evidence-label">' +
              U.escapeHtml(evidence.items_label || 'Detected:') + '</div>' +
              '<ul class="why-fail__evidence-list">';
            evidence.items.forEach(function (item) {
              html += '<li>' + U.escapeHtml(item) + '</li>';
            });
            html += '</ul>';
          }

          html += '</div></div>';
        });

        html += '</div></div>';
      } else if (status === 'not_tested') {
        html += '<div style="background: var(--bg-secondary, #f9fafb); border-radius: var(--radius-md); padding: 12px; border-left: 3px solid var(--color-warn, #d97706);">' +
          '<p class="text-sm" style="color: var(--text-secondary); margin: 0;">' +
          'Not enough data was collected to evaluate every required ' + U.escapeHtml(label) + ' check.</p>' +
        '</div>';
      }
      
      return html;
    }

    // Region and technical consent scan
    var ACTION_TEXT = {
      accept_all: 'Accept all', accept: 'Accept', reject_all: 'Reject all', reject: 'Reject',
      reject_non_essential: 'Reject non-essential (necessary only)', manage_preferences: 'Manage preferences',
      save_preferences: 'Save preferences', dismiss: 'Dismiss / close', acknowledge: 'Acknowledge (OK)',
      unclassified: 'Unclassified'
    };
    var NET_CATEGORY_ORDER = ['ANALYTICS', 'ADVERTISING', 'TAG_MANAGER', 'SOCIAL', 'CMP',
      'OTHER_THIRD_PARTY', 'CONTENT_CDN', 'FONT', 'FIRST_PARTY', 'UNKNOWN'];

    function subLabel(text) {
      return '<p class="text-sm" style="color: var(--text-tertiary); font-weight: 600; margin: 12px 0 6px;">' + U.escapeHtml(text) + '</p>';
    }

    function renderApplicability(app) {
      var html = '';
      var assessed = app.regional_compliance === 'assessed';
      html += '<div class="check-item ' + (assessed ? 'check-item--pass' : 'check-item--pending') + '">' +
        '<span class="check-item__icon">' + (assessed ? PASS_ICON : '') + '</span>' +
        '<span class="check-item__label">Region detected: <strong>' + U.escapeHtml(app.region_label || 'Unknown') + '</strong>' +
        (app.confidence && app.confidence !== 'none' ? ' <span style="color: var(--text-tertiary);">(' + U.escapeHtml(app.confidence) + ' confidence)</span>' : '') +
        '</span></div>';
      html += '<p class="text-sm" style="margin: 4px 0 0 34px;">Framework: <strong>' + U.escapeHtml(app.framework_label || 'Not determined') + '</strong>' +
        ' · Regional compliance: <strong>' + (assessed ? 'Assessed' : 'Not assessed') + '</strong></p>';
      html += '<p class="text-sm" style="margin: 6px 0 0 34px; color: var(--text-secondary);">' + U.escapeHtml(app.note || '') + '</p>';
      if (app.evidence && app.evidence.length) {
        html += subLabel('Evidence');
        html += '<ul style="margin: 0; padding: 0; list-style: none;">' + app.evidence.map(function (e) {
          return '<li class="text-sm" style="margin-bottom: 2px;">\u2022 ' + U.escapeHtml(e) + '</li>';
        }).join('') + '</ul>';
      }

      html += subLabel('Frameworks');
      (app.frameworks || []).forEach(function (fw) {
        var cls = fw.applicable ? 'check-item--pass' : 'check-item--pending';
        html += '<div class="check-item ' + cls + '" style="padding: 2px 0;"><span class="check-item__icon">' + (fw.applicable ? PASS_ICON : '') + '</span>' +
          '<span class="check-item__label">' + U.escapeHtml(fw.label) + ' — ' + (fw.applicable ? 'Assessed' : 'Not assessed') +
          '<span style="display:block; font-size: 0.85em; color: var(--text-tertiary);">' + U.escapeHtml(fw.reason || '') + '</span></span></div>';
      });

      if (!(app.evidence && app.evidence.length) && app.signals && app.signals.length) {
        html += subLabel('Region signals');
        html += '<ul style="margin: 0; padding: 0; list-style: none;">' + app.signals.map(function (sig) {
          return '<li class="text-sm" style="margin-bottom: 2px;">• ' + U.escapeHtml(sig.detail) +
            ' <span style="color: var(--text-tertiary);">(' + U.escapeHtml(sig.region) + ', +' + sig.weight + ')</span></li>';
        }).join('') + '</ul>';
      }
      return html;
    }

    function hiddenControlsNote(n, examples) {
      if (!n) return '';
      return '<p class="cev-muted" style="margin-top:6px;">' + n + ' other control' + (n === 1 ? '' : 's') +
        ' in the banner did not match a consent action and ' + (n === 1 ? 'is' : 'are') + ' not listed' +
        ((examples || []).length ? ' (e.g. ' + U.escapeHtml(examples.slice(0, 4).join(', ')) + ')' : '') + '.</p>';
    }

    function renderControlsTable(controls) {
      var all = controls || [];
      controls = all.filter(function (c) { return c.action && c.action !== 'unclassified'; });
      var hidden = all.filter(function (c) { return !c.action || c.action === 'unclassified'; });
      if (!controls.length) {
        if (hidden.length) return hiddenControlsNote(hidden.length, hidden.map(function (c) { return c.label; }));
        return '<p class="text-sm" style="color: var(--text-tertiary);">No controls were found inside a consent banner.</p>';
      }
      var rows = controls.map(function (c) {
        return '<tr>' +
          '<td style="padding:4px 8px; border-bottom:1px solid var(--border, #e5e7eb);">' + U.escapeHtml(c.label) + '</td>' +
          '<td style="padding:4px 8px; border-bottom:1px solid var(--border, #e5e7eb);"><code>' + U.escapeHtml(c.action) + '</code>' +
            '<span style="display:block; font-size:0.85em; color: var(--text-tertiary);">' + U.escapeHtml(ACTION_TEXT[c.action] || c.action) + (c.layer === 2 ? ' · second layer' : '') + '</span></td>' +
          '<td style="padding:4px 8px; border-bottom:1px solid var(--border, #e5e7eb);">' + U.escapeHtml(c.evidence || '') + '</td>' +
          '</tr>';
      }).join('');
      return '<div style="overflow-x:auto;"><table class="text-sm" style="width:100%; border-collapse: collapse;">' +
        '<thead><tr style="text-align:left; color: var(--text-tertiary);">' +
        '<th style="padding:4px 8px;">Displayed text</th><th style="padding:4px 8px;">Detected action</th><th style="padding:4px 8px;">Evidence</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
        hiddenControlsNote(hidden.length, hidden.map(function (c) { return c.label; }));
    }

    function renderNetworkSummary(summary) {
      if (!summary) return '';
      var cats = NET_CATEGORY_ORDER.filter(function (k) { return summary[k]; });
      if (!cats.length) return '';
      return '<ul style="margin: 0; padding: 0; list-style: none;">' + cats.map(function (k) {
        var e = summary[k];
        var note = '';
        if (k === 'TAG_MANAGER') note = ' — observation (not tracking by itself)';
        else if ((k === 'ANALYTICS' || k === 'ADVERTISING') && e.tracking_count) note = ' — ' + e.tracking_count + ' collection request(s): tracking activity';
        else if (k === 'ANALYTICS' || k === 'ADVERTISING') note = ' — library loads only, no collection observed';
        return '<li class="text-sm" style="margin-bottom: 2px;">• <strong>' + U.escapeHtml(e.label || k) + '</strong>: ' + e.count + ' request(s)' +
          (e.vendors && e.vendors.length ? ' (' + U.escapeHtml(e.vendors.join(', ')) + ')' : '') + U.escapeHtml(note) + '</li>';
      }).join('') + '</ul>';
    }

    function renderTechnicalScan(ts) {
      var html = '';
      var banner = ts.banner || {};
      var src = banner.source === 'rendered' ? 'Rendered consent banner' : banner.source === 'static_markup' ? 'Consent banner markup (static HTML)' : 'Not found';
      html += '<div class="check-item ' + (banner.detected ? 'check-item--pass' : 'check-item--fail') + '"><span class="check-item__icon">' + (banner.detected ? PASS_ICON : FAIL_ICON) + '</span>' +
        '<span class="check-item__label">Consent banner ' + (banner.detected ? 'detected' : 'not detected') +
        (banner.detected ? '<span style="display:block; font-size: 0.85em; color: var(--text-tertiary);">Evidence: ' + U.escapeHtml(src) +
          (banner.container ? ' · container ' + U.escapeHtml(banner.container) : '') +
          (banner.frame && banner.frame !== 'main' ? ' · iframe ' + U.escapeHtml(banner.frame) : '') + '</span>' : '') +
        '</span></div>';

      if (ts.scan && ts.scan.scan_id) {
        html += '<p class="text-sm" style="margin: 4px 0 0 34px; color: var(--text-tertiary);">Fresh scan ' + U.escapeHtml(ts.scan.scan_id) +
          (ts.scan.fresh_browser_contexts ? ' · ' + ts.scan.fresh_browser_contexts + ' fresh browser context(s)' : '') +
          (ts.scan.started_at ? ' · ' + U.escapeHtml(String(ts.scan.started_at).replace('T', ' ').slice(0, 19)) + ' UTC' : '') + '</p>';
      }

      html += subLabel('Banner controls');
      html += renderControlsTable(ts.controls);

      var pref = ts.preferences || {};
      if (pref.panel_verified === true || pref.panel_verified === false) {
        html += '<div class="check-item ' + (pref.panel_verified ? 'check-item--pass' : 'check-item--fail') + '" style="padding: 6px 0 0;">' +
          '<span class="check-item__icon">' + (pref.panel_verified ? PASS_ICON : FAIL_ICON) + '</span>' +
          '<span class="check-item__label">Manage preferences clicked → preference panel ' + (pref.panel_verified ? 'appeared' : 'did not appear') +
          (pref.panel_toggle_count ? ' (' + pref.panel_toggle_count + ' category toggle(s))' : '') + '</span></div>';
      }

      var checks = ts.checks || {};
      var details = ts.check_details || {};
      html += subLabel('Technical checks');
      html += GDPR_CHECK_ITEMS.map(function (item) {
        var r = checkResultFromValue(checks[item.key]);
        var cls = !r.tested ? 'check-item--pending' : (r.ok ? 'check-item--pass' : 'check-item--fail');
        return '<div class="check-item ' + cls + '" style="padding: 2px 0;"><span class="check-item__icon">' + (!r.tested ? '' : (r.ok ? PASS_ICON : FAIL_ICON)) + '</span>' +
          '<span class="check-item__label">' + U.escapeHtml(item.label) + (r.tested ? '' : ' (not tested)') +
          (details[item.key] ? '<span style="display:block; font-size: 0.85em; color: var(--text-tertiary);">' + U.escapeHtml(details[item.key]) + '</span>' : '') +
          '</span></div>';
      }).join('');

      var net = ts.network || {};
      if (net.before_consent) {
        html += subLabel('Network before consent');
        html += renderNetworkSummary(net.before_consent);
      }
      var ck = ts.cookies_before_consent || {};
      var ckGroups = [
        ['consent_required', 'Analytics / marketing (consent required)'],
        ['consent_management', 'Consent management (CMP storage)'],
        ['essential', 'Essential / security'],
        ['functional', 'Functional'],
        ['unknown', 'Unknown (needs review — not counted as a failure)']
      ].filter(function (g) { return ck[g[0]] && ck[g[0]].length; });
      if (ckGroups.length) {
        html += subLabel('Cookies before consent');
        html += '<ul style="margin: 0; padding: 0; list-style: none;">' + ckGroups.map(function (g) {
          return '<li class="text-sm" style="margin-bottom: 4px;">• <strong>' + U.escapeHtml(g[1]) + '</strong>: ' +
            U.escapeHtml(ck[g[0]].slice(0, 8).join('; ')) + (ck[g[0]].length > 8 ? ' …' : '') + '</li>';
        }).join('') + '</ul>';
      }
      return html;
    }

    function technicalBand(ts) {
      var st = complianceStatus(GDPR_CHECK_ITEMS, ts.checks || {});
      return st === 'pass' ? 'good' : st === 'fail' ? 'bad' : 'mid';
    }

    // Consent evidence from report_view (same as the PDF and exports)
    var KIND_LABEL = { tracking: 'Tracking', observation: 'Observation', infrastructure: 'Infrastructure', other: 'Unclassified' };
    var STATE_CHIP = { pass: ['pass', 'Passed'], fail: ['fail', 'Failed'], not_tested: ['', 'Not tested'], not_assessed: ['', 'Not assessed'] };

    function chip(cls, text) {
      return '<span class="cev-chip' + (cls ? ' cev-chip--' + cls : '') + '">' + U.escapeHtml(text) + '</span>';
    }

    /* The exact requests behind a tile (vendor + address). */
    function tileDetails(items) {
      if (!items || !items.length) return '';
      var row = function (i) {
        return '<li><strong>' + U.escapeHtml(i.vendor || i.category || '') + '</strong>' +
          (i.kind === 'observation' ? ' <em>(loaded, ' + U.escapeHtml((i.note || 'not tracking by itself').toLowerCase()) + ')</em>' : '') +
          (i.request ? '<br><code>' + U.escapeHtml(i.request) + '</code>' : '') + '</li>';
      };
      return '<details class="cev-tile__details"><summary>Show the ' + items.length +
        (items.length === 1 ? ' request' : ' requests') + '</summary><ul>' + items.map(row).join('') + '</ul></details>';
    }

    function renderConsentDashboard(view) {
      var st = view.status || {};
      var html = '<div class="cev-status">' +
        '<span>Region: <strong>' + U.escapeHtml(st.region_label || 'Unknown') + '</strong>' +
          (st.confidence ? ' (' + U.escapeHtml(st.confidence) + ' confidence)' : '') + '</span>' +
        '<span>Framework: <strong>' + U.escapeHtml(st.framework_label || 'Not determined') + '</strong></span>' +
        '<span>Regional compliance: <strong>' + U.escapeHtml(st.regional_compliance_label || '') + '</strong></span>' +
        (st.scan_id ? '<span class="cev-status__scan">Fresh scan ' + U.escapeHtml(st.scan_id) +
          (st.fresh_browser_contexts ? ' · ' + st.fresh_browser_contexts + ' clean browser session(s)' : '') + '</span>' : '') +
        '</div>';
      html += '<div class="cev-tiles">' + (view.tiles || []).map(function (t) {
        return '<div class="cev-tile" data-state="' + U.escapeHtml(t.state) + '">' +
          '<span class="cev-tile__label">' + U.escapeHtml(t.label) + '</span>' +
          '<span class="cev-tile__value">' + U.escapeHtml(t.value) + '</span>' +
          (t.sub ? '<span class="cev-tile__sub">' + U.escapeHtml(t.sub) + '</span>' : '') +
          tileDetails(t.details) +
          '</div>';
      }).join('') + '</div>';
      return html;
    }

    function renderApplicabilityView(view) {
      var st = view.status || {};
      var html = '<div class="cev">';
      html += '<div class="cev-frameworks">' + (view.frameworks || []).map(function (fw) {
        var c = STATE_CHIP[fw.status] || ['', fw.status_label || fw.status];
        return '<div class="cev-fw" data-status="' + U.escapeHtml(fw.status) + '">' +
          '<span class="cev-fw__name">' + U.escapeHtml(fw.label) + '</span>' +
          '<span>' + chip(c[0], fw.applicable ? (fw.status_label || c[1]) : 'Not assessed') + '</span>' +
          (fw.reason ? '<span class="cev-fw__reason">' + U.escapeHtml(fw.reason) + '</span>' : '') +
          '</div>';
      }).join('') + '</div>';
      if (st.note) html += '<p class="cev-muted">' + U.escapeHtml(st.note) + '</p>';
      if (st.evidence && st.evidence.length) {
        html += '<div class="cev-block"><p class="cev-block__title">Region evidence</p><ul class="cev-evidence">' +
          st.evidence.map(function (e) { return '<li>' + U.escapeHtml(e) + '</li>'; }).join('') + '</ul></div>';
      } else {
        html += '<p class="cev-muted">No regional signals were found on the site.</p>';
      }
      return html + '</div>';
    }

    function renderNetworkTable(rows) {
      if (!rows || !rows.length) return '<p class="cev-muted">No requests captured.</p>';
      return '<div class="cev-table-wrap"><table class="cev-table"><thead><tr>' +
        '<th>Category</th><th>Requests</th><th>Classification</th><th>Vendors</th></tr></thead><tbody>' +
        rows.map(function (r) {
          return '<tr><td>' + U.escapeHtml(r.label) + '</td><td>' + r.count + '</td>' +
            '<td>' + chip(r.kind, KIND_LABEL[r.kind] || r.kind) + '<small>' + U.escapeHtml(r.note) + '</small></td>' +
            '<td>' + U.escapeHtml((r.vendors || []).join(', ') || '—') + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    }

    function renderTechnicalView(view) {
      var html = '<div class="cev">';

      html += '<div class="cev-block"><p class="cev-block__title">Banner controls</p>';
      var shownControls = (view.controls || []).filter(function (c) { return c.action && c.action !== 'unclassified'; });
      var hid = view.controls_hidden || view.controlsHidden || { count: (view.controls || []).length - shownControls.length, examples: [] };
      if (shownControls.length) {
        html += '<div class="cev-table-wrap"><table class="cev-table"><thead><tr>' +
          '<th>Displayed text</th><th>Detected action</th><th>Evidence</th></tr></thead><tbody>' +
          shownControls.map(function (c) {
            return '<tr><td>' + U.escapeHtml(c.label) + '</td><td>' + chip('action', c.action) +
              '<small>' + U.escapeHtml(ACTION_TEXT[c.action] || c.action_label || '') + (c.layer === 2 ? ' · preference panel' : '') + '</small></td>' +
              '<td>' + U.escapeHtml(c.evidence) + '</td></tr>';
          }).join('') + '</tbody></table></div>' + hiddenControlsNote(hid.count, hid.examples);
      } else if (hid.count) {
        html += hiddenControlsNote(hid.count, hid.examples);
      } else {
        html += '<p class="cev-muted">No controls were found inside a consent banner.</p>';
      }
      html += '</div>';

      html += '<div class="cev-block"><p class="cev-block__title">Technical checks</p>' +
        (view.technical_checks || []).map(function (c) {
          var r = c.state === 'pass' ? { ok: true, tested: true } : c.state === 'fail' ? { ok: false, tested: true } : { ok: false, tested: false };
          var cls = !r.tested ? 'check-item--pending' : (r.ok ? 'check-item--pass' : 'check-item--fail');
          return '<div class="check-item ' + cls + '" style="padding: 2px 0;"><span class="check-item__icon">' + (!r.tested ? '' : (r.ok ? PASS_ICON : FAIL_ICON)) + '</span>' +
            '<span class="check-item__label">' + U.escapeHtml(c.label) + (r.tested ? '' : ' (not tested)') +
            (c.detail ? '<span style="display:block; font-size: 0.85em; color: var(--text-tertiary);">' + U.escapeHtml(c.detail) + '</span>' : '') +
            '</span></div>';
        }).join('') + '</div>';

      var net = view.network || {};
      if (net.before_consent) {
        html += '<div class="cev-block"><p class="cev-block__title">Network before consent</p>' + renderNetworkTable(net.before_consent) + '</div>';
      }
      if (net.after_reject !== undefined || net.after_accept !== undefined) {
        html += '<details class="cev-block"><summary>Network after Reject / after Accept</summary>' +
          (net.after_reject !== undefined ? '<p class="cev-muted">After Reject</p>' + renderNetworkTable(net.after_reject) : '') +
          (net.after_reject_next_page !== undefined ? '<p class="cev-muted">After Reject — next page view (choice saved, page reloaded)</p>' + renderNetworkTable(net.after_reject_next_page) : '') +
          (net.after_accept !== undefined ? '<p class="cev-muted">After Accept</p>' + renderNetworkTable(net.after_accept) : '') +
          '</details>';
      }

      if (view.cookies && view.cookies.length) {
        var toneChip = { fail: 'fail', pass: 'pass', info: 'observation', neutral: '' };
        html += '<div class="cev-block"><p class="cev-block__title">Cookies before consent</p><div class="cev-cookies">' +
          view.cookies.map(function (g) {
            return '<div class="cev-cookie-group">' + chip(toneChip[g.tone], g.count + ' · ' + g.label) +
              '<span class="cev-cookie-group__items">' + U.escapeHtml(g.items.slice(0, 8).join('; ')) + (g.items.length > 8 ? ' …' : '') + '</span></div>';
          }).join('') + '</div></div>';
      }

      if (view.pipeline && view.pipeline.length) {
        html += '<details class="cev-block"><summary>Scan pipeline — ' + view.pipeline.length + ' steps (fresh scan)</summary><ol class="cev-pipeline">' +
          view.pipeline.map(function (p) {
            var cls = p.status === 'done' ? 'pass' : p.status === 'not_tested' ? 'warn' : '';
            return '<li><span class="cev-pipeline__n">' + p.step + '</span><span>' + U.escapeHtml(p.name) + '</span><span>' + chip(cls, p.status) + '</span>' +
              '<span class="cev-pipeline__detail">' + U.escapeHtml(p.detail || '') + '</span></li>';
          }).join('') + '</ol>' +
          ((view.legs && view.legs.length) ? '<ul class="cev-evidence" style="margin-top:8px;">' + view.legs.map(function (l) {
            return '<li>' + U.escapeHtml(l) + '</li>'; }).join('') + '</ul>' : '') +
          '</details>';
      }
      return html + '</div>';
    }

    function renderShotsView(view) {
      return '<div class="cev-block"><p class="cev-block__title">Evidence screenshots</p><div class="cev-shots">' +
        (view.screenshots || []).map(function (sh) {
          var full = sh.url ? (window.APP_CONFIG.API_ORIGIN + sh.url) : null;
          return '<div class="cev-shot"><div class="cev-shot__frame">' +
            (full ? '<img src="' + U.escapeHtml(full) + '" alt="' + U.escapeHtml(sh.label) + ' screenshot" loading="lazy">'
                  : '<span class="cev-shot__empty">Not captured</span>') +
            '</div><div class="cev-shot__meta"><span>' + U.escapeHtml(sh.label) + '</span>' +
            (full ? '<a href="' + U.escapeHtml(full) + '" download>Download</a>' : '') + '</div></div>';
        }).join('') + '</div></div>';
    }

    function renderConsent(consent) {
      var chip = document.getElementById('consentScoreChip');
      var foundationGrid = document.getElementById('consentFoundationCheckGrid');
      var runtimeWrap = document.getElementById('consentRuntimeCheckWrap');
      var runtimeGrid = document.getElementById('consentRuntimeCheckGrid');
      var gdprSection = document.getElementById('consentGdprSection');
      var gdprGrid = document.getElementById('consentGdprCheckGrid');
      var ccpaSection = document.getElementById('consentCcpaSection');
      var ccpaGrid = document.getElementById('consentCcpaCheckGrid');
      var shotWrap = document.getElementById('consentScreenshotWrap');
      var appSection = document.getElementById('consentApplicabilitySection');
      var appGrid = document.getElementById('consentApplicabilityGrid');
      var techSection = document.getElementById('consentTechnicalSection');
      var techGrid = document.getElementById('consentTechnicalGrid');
      var dpdpSection = document.getElementById('consentDpdpSection');
      var dpdpGrid = document.getElementById('consentDpdpCheckGrid');

      if (!consent) {
        if (appSection) appSection.style.display = 'none';
        if (techSection) techSection.style.display = 'none';
        if (dpdpSection) dpdpSection.style.display = 'none';
        if (chip) chip.textContent = 'Not scanned';
        if (foundationGrid) foundationGrid.innerHTML = '<p class="text-sm" style="color: var(--text-tertiary);">This audit didn\'t include the consent module.</p>';
        if (runtimeWrap) runtimeWrap.style.display = 'none';
        if (gdprSection) gdprSection.style.display = 'none';
        if (ccpaSection) ccpaSection.style.display = 'none';
        if (shotWrap) shotWrap.innerHTML = '';
        return;
      }

      if (chip) chip.textContent = consent.consentScore + ' / 100';
      setModuleStatus('consentScoreChip', 'consentStatusIcon', consent.consentScore);

      var view = consent.reportView || null;
      var useView = !!(view && !view.legacy);
      var dash = document.getElementById('consentEvidenceDashboard');
      if (dash) {
        if (useView) { dash.innerHTML = renderConsentDashboard(view); dash.style.display = ''; }
        else { dash.innerHTML = ''; dash.style.display = 'none'; }
      }

      // Foundation checks (older audits only)
      if (foundationGrid && useView) {
        foundationGrid.innerHTML = '';
        foundationGrid.style.display = 'none';
      } else if (foundationGrid) {
        var foundationItems = [
          { label: 'Cookie banner detected', ok: consent.hasCookieBanner },
          { label: 'Blocks trackers before consent', ok: consent.bannerBlocksScriptsPreConsent }
        ];
        foundationGrid.innerHTML = foundationItems.map(renderCheckItemRow).join('');
      }

      // Live checks (only if tested); null means not tested.
      if (runtimeWrap) {
        if (useView) {
          // The tiles above show these results.
          runtimeWrap.style.display = 'none';
        } else if (consent.runtimeTested) {
          runtimeWrap.style.display = '';
          if (runtimeGrid) {
            var rr = consent.runtimeResult || {};
            // runtime_result keys arrive in camelCase.
            var pick = function (camel, snake) { return rr[camel] !== undefined ? rr[camel] : rr[snake]; };
            var runtimeItems = [
              Object.assign({ label: 'Reject blocks tracking' }, checkResultFromValue(pick('rejectBlocksTracking', 'reject_blocks_tracking'))),
              Object.assign({ label: 'Accept allows tracking' }, checkResultFromValue(pick('acceptAllowsTracking', 'accept_allows_tracking'))),
              Object.assign({ label: 'Personalize exposes controls' }, checkResultFromValue(pick('personalizeExposesControls', 'personalize_exposes_controls')))
            ];
            runtimeGrid.innerHTML = runtimeItems.map(renderCheckItemRow).join('');
            // Set runtime section status based on results
            var runtimeBand = runtimeItems.some(function (item) { return item.tested && !item.ok; }) ? 'bad' :
                              runtimeItems.every(function (item) { return item.tested; }) ? 'good' : 'mid';
            setAnalyticsSectionStatus('consentRuntimeStatusIcon', runtimeBand);
          }
        } else {
          runtimeWrap.style.display = 'none';
        }
      }

      // Only laws that apply are shown; older audits show both GDPR and CCPA.
      var app = consent.applicability || {};
      var hasApp = !!(app.frameworks && app.frameworks.length);
      var applies = function (fw) {
        return !hasApp || (app.applicable_frameworks || []).indexOf(fw) !== -1;
      };

      if (appSection && appGrid) {
        if (useView) {
          appGrid.innerHTML = renderApplicabilityView(view);
          appSection.style.display = '';
          setAnalyticsSectionStatus('consentApplicabilityStatusIcon', app.regional_compliance === 'assessed' ? 'good' : 'mid');
        } else if (hasApp) {
          appGrid.innerHTML = renderApplicability(app);
          appSection.style.display = '';
          setAnalyticsSectionStatus('consentApplicabilityStatusIcon', app.regional_compliance === 'assessed' ? 'good' : 'mid');
        } else {
          appSection.style.display = 'none';
        }
      }

      var ts = consent.technicalScan || {};
      if (techSection && techGrid) {
        if (useView) {
          techGrid.innerHTML = renderTechnicalView(view);
          techSection.style.display = '';
          setAnalyticsSectionStatus('consentTechnicalStatusIcon', technicalBand(ts));
        } else if (ts.checks) {
          techGrid.innerHTML = renderTechnicalScan(ts);
          techSection.style.display = '';
          setAnalyticsSectionStatus('consentTechnicalStatusIcon', technicalBand(ts));
        } else {
          techSection.style.display = 'none';
        }
      }

      if (dpdpSection && dpdpGrid) {
        var dpdpFw = (app.frameworks || []).filter(function (f) { return f.key === 'dpdp' && f.applicable; })[0];
        var dpdp = dpdpFw && dpdpFw.assessment;
        if (dpdp && dpdp.checks) {
          var dpdpItems = (dpdp.order || Object.keys(dpdp.checks)).map(function (k) {
            return { key: k, label: (dpdp.labels || {})[k] || k, required: ['refusal_blocks_tracking', 'dpdp_referenced', 'notice_rights_described'].indexOf(k) === -1 };
          });
          var dpdpStatus = complianceStatus(dpdpItems, dpdp.checks);
          dpdpGrid.innerHTML = renderComplianceSummary('DPDP', dpdpStatus, dpdpItems, dpdp.checks, dpdp.evidence || {});
          dpdpSection.style.display = '';
          setAnalyticsSectionStatus('consentDpdpStatusIcon', dpdpStatus === 'pass' ? 'good' : dpdpStatus === 'fail' ? 'bad' : 'mid');
        } else {
          dpdpSection.style.display = 'none';
        }
      }

      // GDPR
      if (gdprSection && !applies('gdpr')) {
        gdprSection.style.display = 'none';
      } else if (gdprGrid && gdprSection) {
        var gdprChecks = consent.gdprChecks || {};
        var gdprEvidence = consent.gdprCheckEvidence || {};
        var gdprStatus = complianceStatus(GDPR_CHECK_ITEMS, gdprChecks);
        gdprGrid.innerHTML = renderComplianceSummary('GDPR', gdprStatus, GDPR_CHECK_ITEMS, gdprChecks, gdprEvidence);
        gdprSection.style.display = '';
        // Same result as the section above.
        var gdprBand = gdprStatus === 'pass' ? 'good' : gdprStatus === 'fail' ? 'bad' : 'mid';
        setAnalyticsSectionStatus('consentGdprStatusIcon', gdprBand);
      }

      // CCPA
      if (ccpaSection && !applies('ccpa')) {
        ccpaSection.style.display = 'none';
      } else if (ccpaGrid && ccpaSection) {
        var ccpaChecks = consent.ccpaChecks || {};
        var ccpaEvidence = consent.ccpaCheckEvidence || {};
        var ccpaStatus = complianceStatus(CCPA_CHECK_ITEMS, ccpaChecks);
        ccpaGrid.innerHTML = renderComplianceSummary('CCPA', ccpaStatus, CCPA_CHECK_ITEMS, ccpaChecks, ccpaEvidence);
        ccpaSection.style.display = '';
        // Same result as the section above.
        var ccpaBand = ccpaStatus === 'pass' ? 'good' : ccpaStatus === 'fail' ? 'bad' : 'mid';
        setAnalyticsSectionStatus('consentCcpaStatusIcon', ccpaBand);
      }

      if (shotWrap && useView) {
        shotWrap.innerHTML = renderShotsView(view);
      } else if (shotWrap) {
        // Use the four browser screenshots; fall back to the single banner screenshot.
        var shots = [
          { label: 'Initial banner', url: consent.bannerScreenshotUrl },
          { label: 'Personalize / Manage Preferences', url: consent.preferencesScreenshotUrl },
          { label: 'After Reject', url: consent.rejectScreenshotUrl },
          { label: 'After Accept', url: consent.acceptScreenshotUrl }
        ].filter(function (s) { return !!s.url; });

        if (shots.length) {
          shotWrap.innerHTML =
            '<div class="screenshot-strip">' +
              shots.map(function (s) {
                var fullUrl = window.APP_CONFIG.API_ORIGIN + s.url;
                return '<div class="screenshot-strip__item" style="background:none; align-items:stretch; padding:0; flex-direction:column;">' +
                  '<img src="' + U.escapeHtml(fullUrl) + '" alt="' + U.escapeHtml(s.label) + ' screenshot" style="width:100%; height:160px; object-fit:contain; border-radius: var(--radius-md);">' +
                  '<div style="display:flex; align-items:center; justify-content:space-between; margin-top:4px; gap:8px;">' +
                    '<span class="text-sm" style="color: var(--text-tertiary);">' + U.escapeHtml(s.label) + '</span>' +
                    '<a href="' + U.escapeHtml(fullUrl) + '" download class="text-sm" style="color: var(--primary, #2563EB); white-space:nowrap;">Download</a>' +
                  '</div>' +
                '</div>';
              }).join('') +
            '</div>';
        } else {
          shotWrap.innerHTML =
            '<div class="screenshot-strip" style="grid-template-columns: 1fr;">' +
              '<div class="screenshot-strip__item"><span>No screenshot captured</span></div>' +
            '</div>';
        }
      }
    }

    // Tool key -> name (same as backend TRACKER_DISPLAY_NAMES).
    var VENDOR_LABELS = {
      ga4: 'Google Analytics 4', gtm: 'Google Tag Manager', adobe: 'Adobe Analytics',
      piano: 'Piano Analytics', clarity: 'Microsoft Clarity', hotjar: 'Hotjar',
      meta_pixel: 'Meta Pixel', metaPixel: 'Meta Pixel', linkedin: 'LinkedIn Insight Tag', tiktok: 'TikTok Pixel', tagcommander: 'TagCommander'
    };

    function analyticsStatusBadge(status) {
      if (status === 'passed') return '<span style="color: var(--success, #16a34a);">Passed</span>';
      if (status === 'failed') return '<span style="color: var(--danger, #dc2626);">Failed</span>';
      if (status === 'not_applicable') return '<span style="color: var(--text-tertiary);">—</span>';
      return '<span style="color: var(--text-tertiary);">Not tested</span>';
    }

    // Status icon for an Analytics sub-section.
    function setAnalyticsSectionStatus(iconId, band) {
      var icon = document.getElementById(iconId);
      if (!icon) return;
      if (!band) { icon.style.display = 'none'; return; }
      icon.style.display = '';
      icon.className = 'module-accordion__status module-accordion__status--' + band;
      icon.innerHTML = band === 'good' ? PASS_ICON : (band === 'mid' ? WARN_ICON : FAIL_ICON);
    }

    function renderAnalytics(analytics) {
      var chip = document.getElementById('analyticsScoreChip');
      var overallStatus = document.getElementById('analyticsOverallStatus');
      var overallBadge = document.getElementById('analyticsOverallBadge');
      var emptyMessage = document.getElementById('analyticsEmptyMessage');
      var sections = document.getElementById('analyticsSections');
      var checkGrid = document.getElementById('analyticsCheckGrid');
      var configTable = document.getElementById('analyticsConfigTable');
      var vendorTable = document.getElementById('analyticsVendorTable');
      var eventValidation = document.getElementById('analyticsEventValidation');
      var detail = document.getElementById('analyticsDetail');
      var fullSite = document.getElementById('analyticsFullSite');

      if (!analytics) {
        if (chip) chip.style.display = 'none';
        if (overallStatus) overallStatus.style.display = 'none';
        if (sections) sections.style.display = 'none';
        if (emptyMessage) {
          emptyMessage.style.display = '';
          emptyMessage.textContent = 'This audit didn\'t include the analytics module.';
        }
        if (checkGrid) checkGrid.innerHTML = '';
        if (configTable) configTable.innerHTML = '';
        if (vendorTable) vendorTable.innerHTML = '';
        if (eventValidation) eventValidation.innerHTML = '';
        if (detail) detail.textContent = '';
        if (fullSite) fullSite.style.display = 'none';
        return;
      }

      if (sections) sections.style.display = '';
      if (emptyMessage) emptyMessage.style.display = 'none';

      if (chip) { chip.style.display = ''; chip.textContent = analytics.analyticsScore + ' / 100'; }

      // Overall Analytics status, from the same score band as the chip.
      if (overallStatus && overallBadge) {
        var overallBand = U.scoreBand(analytics.analyticsScore);
        var overallIcon = overallBand === 'good' ? PASS_ICON : (overallBand === 'mid' ? WARN_ICON : FAIL_ICON);
        overallStatus.style.display = '';
        overallBadge.className = 'analytics-overall-status__badge analytics-overall-status__badge--' + overallBand;
        overallBadge.innerHTML = '<span class="analytics-overall-status__badge-icon">' + overallIcon + '</span>' +
          U.escapeHtml(OVERALL_STATUS_LABELS[overallBand] || '');
      }

      if (checkGrid) {
        var items = [
          { label: 'Any tracker detected', ok: (analytics.trackersDetected || []).length > 0 },
          { label: 'Tag Manager detected', ok: analytics.tagManagerDetected },
          { label: 'Data layer present', ok: analytics.dataLayerPresent },
          // tested = the live check could run; ok = it completed.
          { label: 'Runtime-validated', ok: !!analytics.runtimeTested, tested: !!analytics.runtimeAvailable,
            notTestedReason: 'runtime validation is unavailable in this environment' }
        ];
        checkGrid.innerHTML = items.map(function (item) {
          var tested = item.tested !== false;
          var cls = !tested ? 'check-item--pending' : (item.ok ? 'check-item--pass' : 'check-item--fail');
          var icon = !tested ? '' : (item.ok ? PASS_ICON : FAIL_ICON);
          var suffix = tested ? '' : ' (' + (item.notTestedReason || 'not tested') + ')';
          return '<div class="check-item ' + cls + '"><span class="check-item__icon">' + icon + '</span><span class="check-item__label">' + U.escapeHtml(item.label) + U.escapeHtml(suffix) + '</span></div>';
        }).join('');
      }

      // Only detected tools appear in vendorConfigs.
      var vendorConfigs = analytics.vendorConfigs || {};
      var detectedKeys = Object.keys(vendorConfigs);
      var runtimeVendors = (analytics.runtimeResult && analytics.runtimeResult.vendors) || {};

      // Configuration: good if any tool was found.
      setAnalyticsSectionStatus('analyticsConfigStatusIcon', detectedKeys.length ? 'good' : 'bad');

      // Configuration: IDs per detected tool.
      if (configTable) {
        if (!detectedKeys.length) {
          configTable.innerHTML = '<p class="text-sm" style="color: var(--text-tertiary);">No analytics vendors detected on this page.</p>';
        } else {
          configTable.innerHTML =
            '<div style="overflow-x:auto;">' +
            '<table class="text-sm" style="width:100%; border-collapse:collapse;">' +
              '<thead><tr style="text-align:left; color: var(--text-tertiary);">' +
                '<th style="padding:6px 10px;">Vendor</th><th style="padding:6px 10px;">ID / Configuration</th>' +
              '</tr></thead><tbody>' +
              detectedKeys.map(function (k) {
                var ids = vendorConfigs[k] || [];
                var idText = ids.length ? U.escapeHtml(ids.join(', ')) : '<span style="color: var(--text-tertiary);">Detected — no ID extracted</span>';
                return '<tr style="border-top:1px solid var(--border, #e5e7eb);">' +
                  '<td style="padding:6px 10px;">' + U.escapeHtml(VENDOR_LABELS[k] || k) + '</td>' +
                  '<td style="padding:6px 10px;">' + idText + '</td>' +
                '</tr>';
              }).join('') +
              '</tbody></table></div>';
        }
      }

      // Detection & live check: every detected tool, even if it never fired.
      if (vendorTable) {
        if (!detectedKeys.length) {
          vendorTable.innerHTML = '';
        } else {
          vendorTable.innerHTML =
            '<div style="overflow-x:auto;">' +
            '<table class="text-sm" style="width:100%; border-collapse:collapse;">' +
              '<thead><tr style="text-align:left; color: var(--text-tertiary);">' +
                '<th style="padding:6px 10px;">Vendor</th><th style="padding:6px 10px;">Detection</th>' +
                '<th style="padding:6px 10px;">Runtime</th><th style="padding:6px 10px;">Page View</th>' +
                '<th style="padding:6px 10px;">Scroll</th><th style="padding:6px 10px;">Click</th>' +
              '</tr></thead><tbody>' +
              detectedKeys.map(function (k) {
                var v = runtimeVendors[k];
                var runtimeCol = !analytics.runtimeAvailable
                  ? '<span style="color: var(--text-tertiary);">Not tested</span>'
                  : (v ? analyticsStatusBadge(sk(v, 'page_view_status')) : '<span style="color: var(--danger, #dc2626);">Failed</span>');
                return '<tr style="border-top:1px solid var(--border, #e5e7eb);">' +
                  '<td style="padding:6px 10px;">' + U.escapeHtml(VENDOR_LABELS[k] || k) + '</td>' +
                  '<td style="padding:6px 10px;">' + statusIcon('pass') + '</td>' +
                  '<td style="padding:6px 10px;">' + runtimeCol + '</td>' +
                  '<td style="padding:6px 10px;">' + (v ? analyticsStatusBadge(sk(v, 'page_view_status')) : '<span style="color: var(--text-tertiary);">Not tested</span>') + '</td>' +
                  '<td style="padding:6px 10px;">' + (v ? analyticsStatusBadge(sk(v, 'scroll_status')) : '<span style="color: var(--text-tertiary);">Not tested</span>') + '</td>' +
                  '<td style="padding:6px 10px;">' + (v ? analyticsStatusBadge(sk(v, 'click_status')) : '<span style="color: var(--text-tertiary);">Not tested</span>') + '</td>' +
                '</tr>';
              }).join('') +
              '</tbody></table></div>';
        }
      }

      // Explain why the live check didn't run.
      if (vendorTable && !analytics.runtimeAvailable && detectedKeys.length) {
        var rtErr = (analytics.runtimeResult && analytics.runtimeResult.error) || '';
        vendorTable.insertAdjacentHTML('beforeend',
          '<p class="rp-note" style="margin:10px 0 0;">The live browser check (Page View / Scroll / Click) could not run for this audit' +
          (rtErr ? ': <code style="font-size:0.95em;">' + U.escapeHtml(String(rtErr).slice(0, 300)) + '</code>' : '.') +
          ' Re-run the audit to try again.</p>');
      }

      if (vendorTable && analytics.runtimeAvailable && analytics.runtimeResult && analytics.runtimeResult.source === 'journey') {
        var jErr = analytics.runtimeResult.analyticsRuntimeError || analytics.runtimeResult.analytics_runtime_error || '';
        vendorTable.insertAdjacentHTML('beforeend',
          '<p class="rp-note" style="margin:10px 0 0;">Page View results here come from the Journey Map\'s browser pass ' +
          '(every scanned page loaded with consent accepted), because the Analytics module\'s own live check could not run' +
          (jErr ? ' (<code style="font-size:0.95em;">' + U.escapeHtml(String(jErr).slice(0, 200)) + '</code>)' : '') +
          '. Scroll and Click were not tested.</p>');
      }

      // Status: mid if not run, good if all page views fired, mid if some, bad if none.
      if (!analytics.runtimeAvailable) {
        setAnalyticsSectionStatus('analyticsDetectionStatusIcon', detectedKeys.length ? 'mid' : 'bad');
      } else {
        var firedCount = detectedKeys.filter(function (k) {
          return runtimeVendors[k] && sk(runtimeVendors[k], 'page_view_status') === 'passed';
        }).length;
        var detectionBand = !detectedKeys.length ? 'bad'
          : (firedCount === detectedKeys.length ? 'good' : (firedCount > 0 ? 'mid' : 'bad'));
        setAnalyticsSectionStatus('analyticsDetectionStatusIcon', detectionBand);
      }

      // Event validation: live evidence only.
      if (eventValidation) {
        var runtimeKeys = Object.keys(runtimeVendors);

        // Status: mid if not run, bad if nothing captured, mid on duplicates, else good.
        if (!analytics.runtimeAvailable) {
          setAnalyticsSectionStatus('analyticsEventStatusIcon', 'mid');
        } else if (!runtimeKeys.length) {
          setAnalyticsSectionStatus('analyticsEventStatusIcon', 'bad');
        } else {
          var hasDuplicatePv = runtimeKeys.some(function (k) { return sk(runtimeVendors[k], 'duplicate_page_view'); });
          setAnalyticsSectionStatus('analyticsEventStatusIcon', hasDuplicatePv ? 'mid' : 'good');
        }

        if (!analytics.runtimeAvailable || !runtimeKeys.length) {
          eventValidation.innerHTML = '<p class="text-sm" style="color: var(--text-tertiary);">' +
            (analytics.runtimeAvailable ? 'No vendor requests captured during the runtime pass.' : 'Runtime validation was not performed for this audit.') +
            '</p>';
        } else {
          eventValidation.innerHTML =
            '<div style="overflow-x:auto;">' +
            '<table class="text-sm" style="width:100%; border-collapse:collapse;">' +
              '<thead><tr style="text-align:left; color: var(--text-tertiary);">' +
                '<th style="padding:6px 10px;">Vendor</th><th style="padding:6px 10px;">Custom Event</th>' +
                '<th style="padding:6px 10px;">Duplicate PV</th><th style="padding:6px 10px;">Requests</th>' +
                '<th style="padding:6px 10px;">Events observed</th>' +
              '</tr></thead><tbody>' +
              runtimeKeys.map(function (k) {
                var v = runtimeVendors[k];
                return '<tr style="border-top:1px solid var(--border, #e5e7eb);">' +
                  '<td style="padding:6px 10px;">' + U.escapeHtml(sk(v, 'vendor_name') || VENDOR_LABELS[k] || k) + '</td>' +
                  '<td style="padding:6px 10px;">' + analyticsStatusBadge(sk(v, 'custom_event_status')) + '</td>' +
                  '<td style="padding:6px 10px;">' + (sk(v, 'duplicate_page_view') ? '<span style="color: var(--danger, #dc2626);">Yes</span>' : 'No') + '</td>' +
                  '<td style="padding:6px 10px;">' + (sk(v, 'captured_request_count') || 0) + '</td>' +
                  '<td style="padding:6px 10px;">' + U.escapeHtml((sk(v, 'event_names') || []).join(', ') || '—') + '</td>' +
                '</tr>';
              }).join('') +
              '</tbody></table></div>';
        }
      }

      // Every tracking service seen in the browser (including ones loaded by a tag manager).
      var observedTags = (analytics.runtimeResult && (analytics.runtimeResult.observedTags || analytics.runtimeResult.observed_tags)) || [];
      if (vendorTable && observedTags.length) {
        var CAT = { TAG_MANAGER: 'Tag manager', ANALYTICS: 'Analytics', ADVERTISING: 'Advertising' };
        var PH = { load: 'page load', scroll: 'scroll', click: 'click' };
        vendorTable.insertAdjacentHTML('beforeend',
          '<p class="text-sm" style="margin:16px 0 6px; font-weight:600;">Vendors seen in the live browser check</p>' +
          '<p class="text-sm" style="margin:0 0 8px; color: var(--text-tertiary);">Every analytics, advertising and tag-manager service that loaded or sent data while the page was opened (consent accepted), scrolled and clicked.</p>' +
          '<div style="overflow-x:auto;"><table class="text-sm" style="width:100%; border-collapse:collapse;">' +
            '<thead><tr style="text-align:left; color: var(--text-tertiary);">' +
              '<th style="padding:6px 10px;">Vendor</th><th style="padding:6px 10px;">Type</th>' +
              '<th style="padding:6px 10px;">Requests</th><th style="padding:6px 10px;">Data sent</th>' +
              '<th style="padding:6px 10px;">Seen on</th><th style="padding:6px 10px;">Domain</th>' +
            '</tr></thead><tbody>' +
            observedTags.map(function (o) {
              var sent = sk(o, 'collection_requests') || 0;
              return '<tr style="border-top:1px solid var(--border, #e5e7eb);">' +
                '<td style="padding:6px 10px; font-weight:600;">' + U.escapeHtml(o.vendor === 'Commanders Act' ? 'TagCommander (Commanders Act)' : o.vendor) + '</td>' +
                '<td style="padding:6px 10px;">' + U.escapeHtml(CAT[o.category] || o.category || '') + '</td>' +
                '<td style="padding:6px 10px;">' + (o.requests || 0) + '</td>' +
                '<td style="padding:6px 10px;">' + (sent ? '<span style="color: var(--success, #16a34a);">Yes (' + sent + ')</span>' : '<span style="color: var(--text-tertiary);">Loaded only</span>') + '</td>' +
                '<td style="padding:6px 10px;">' + U.escapeHtml((o.phases || []).map(function (p) { return PH[p] || p; }).join(', ')) + '</td>' +
                '<td style="padding:6px 10px; color: var(--text-tertiary);">' + U.escapeHtml((o.hosts || []).join(', ')) + '</td>' +
              '</tr>';
            }).join('') +
          '</tbody></table></div>');
      }

      if (detail) {
        var trackers = (analytics.trackersDetected || []).slice();
        observedTags.forEach(function (o) {
          var name = o.vendor === 'Commanders Act' ? 'TagCommander' : o.vendor;
          if (trackers.map(function (t) { return t.toLowerCase(); }).indexOf(name.toLowerCase()) === -1) trackers.push(name);
        });
        detail.textContent = trackers.length
          ? 'Detected: ' + trackers.join(', ') + '.'
          : 'No analytics trackers detected on this page.';
      }

      renderAnalyticsFullSite(analytics);
    }

    /* Full-site analytics */
    // Coverage, per-page results and cross-page findings from the API (full-site audits only).

    // Read keys in either camelCase or snake_case.
    function sk(obj, snake) {
      if (!obj) return undefined;
      if (obj[snake] !== undefined) return obj[snake];
      return obj[snake.replace(/_([a-z0-9])/g, function (_, c) { return c.toUpperCase(); })];
    }

    function renderAnalyticsFullSite(analytics) {
      var section = document.getElementById('analyticsFullSite');
      var coverageGrid = document.getElementById('analyticsCoverageGrid');
      var pageResultsTable = document.getElementById('analyticsPageResultsTable');
      var crossPageTable = document.getElementById('analyticsCrossPageTable');
      var pagesWithIssues = document.getElementById('analyticsPagesWithIssues');
      if (!section) return;

      var pageResults = analytics.pageResults || [];
      var coverage = analytics.siteCoverage || {};
      var crossPageFindings = analytics.crossPageFindings || [];

      if (pageResults.length < 2) {
        section.style.display = 'none';
        return;
      }
      section.style.display = '';

      // Coverage (from the API)
      if (coverageGrid) {
        var coverageItems = [
          { label: 'Pages scanned', value: sk(coverage, 'pages_scanned') },
          { label: 'Pages with Analytics', value: sk(coverage, 'pages_with_analytics') },
          { label: 'Pages without Analytics', value: sk(coverage, 'pages_without_analytics') },
          // Pages only checked as raw HTML on a JavaScript-tagged site: neither with nor without.
          sk(coverage, 'pages_not_verified')
            ? { label: 'Pages not verified (tags added by JavaScript)', value: sk(coverage, 'pages_not_verified') }
            : null,
          { label: 'Pages with runtime failures', value: sk(coverage, 'pages_with_runtime_failures') },
          { label: 'Pages with inconsistencies', value: sk(coverage, 'pages_with_analytics_inconsistencies') },
          { label: 'Pages with findings', value: sk(coverage, 'pages_with_findings') }
        ];
        coverageGrid.innerHTML = coverageItems.filter(Boolean).map(function (item) {
          var val = (item.value === null || item.value === undefined) ? '—' : item.value;
          return '<div class="check-item"><span class="check-item__label">' + U.escapeHtml(item.label) +
            '</span><span style="font-weight:600;">' + val + '</span></div>';
        }).join('');
      }

      // Status: good if every page has analytics and no problems, else mid.
      var coverageHasIssue = !!(sk(coverage, 'pages_without_analytics') ||
        sk(coverage, 'pages_with_analytics_inconsistencies') ||
        sk(coverage, 'pages_with_runtime_failures'));
      setAnalyticsSectionStatus('analyticsCoverageStatusIcon', coverageHasIssue ? 'mid' : 'good');

      // Per-page results
      if (pageResultsTable) {
        pageResultsTable.innerHTML =
          '<div style="overflow-x:auto;">' +
          '<table class="text-sm" style="width:100%; border-collapse:collapse;">' +
            '<thead><tr style="text-align:left; color: var(--text-tertiary);">' +
              '<th style="padding:6px 10px;">Page</th><th style="padding:6px 10px;">HTTP</th><th style="padding:6px 10px;">Trackers Detected</th>' +
              '<th style="padding:6px 10px;">Score</th><th style="padding:6px 10px;">Findings</th>' +
            '</tr></thead><tbody>' +
            pageResults.map(function (p) {
              var pTrackers = sk(p, 'trackers_detected') || [];
              var pFindings = p.findings || [];
              return '<tr style="border-top:1px solid var(--border, #e5e7eb);">' +
                '<td style="padding:6px 10px; word-break:break-all;">' + (p.title ? '<strong>' + U.escapeHtml(p.title) + '</strong><br>' : '') +
                  U.escapeHtml(p.url || '') + '</td>' +
                '<td style="padding:6px 10px;">' + (sk(p, 'status_code') || '—') + '</td>' +
                '<td style="padding:6px 10px;">' + (pTrackers.length
                  ? U.escapeHtml(pTrackers.join(', '))
                  : '<span style="color: var(--text-tertiary);">None detected</span>') + '</td>' +
                '<td style="padding:6px 10px;">' + (p.score != null ? p.score : '—') + '</td>' +
                '<td style="padding:6px 10px;" title="' + U.escapeHtml(pFindings.map(function (f) { return f.title || ''; }).join('; ')) + '">' + pFindings.length + '</td>' +
              '</tr>';
            }).join('') +
            '</tbody></table></div>';
      }

      // Cross-page differences
      if (crossPageTable) {
        if (!crossPageFindings.length) {
          crossPageTable.innerHTML = '<p class="text-sm" style="color: var(--text-tertiary);">No cross-page Analytics inconsistencies were found.</p>';
        } else {
          crossPageTable.innerHTML =
            '<div style="overflow-x:auto;">' +
            '<table class="text-sm" style="width:100%; border-collapse:collapse;">' +
              '<thead><tr style="text-align:left; color: var(--text-tertiary);">' +
                '<th style="padding:6px 10px;">Issue</th><th style="padding:6px 10px;">Description</th>' +
                '<th style="padding:6px 10px;">Affected Pages</th>' +
              '</tr></thead><tbody>' +
              crossPageFindings.map(function (f) {
                var urls = sk(f, 'affected_urls') || [];
                var shown = urls.slice(0, 5).map(U.escapeHtml).join(', ');
                var more = urls.length > 5 ? ' +' + (urls.length - 5) + ' more' : '';
                return '<tr style="border-top:1px solid var(--border, #e5e7eb);">' +
                  '<td style="padding:6px 10px;">' + U.escapeHtml(f.title || '') + '</td>' +
                  '<td style="padding:6px 10px;">' + U.escapeHtml(f.description || '') + '</td>' +
                  '<td style="padding:6px 10px; word-break:break-all;">' + shown + more + '</td>' +
                '</tr>';
              }).join('') +
              '</tbody></table></div>';
        }
      }

      // Pages with analytics issues
      if (pagesWithIssues) {
        var flagged = pageResults.filter(function (p) { return (p.findings || []).length > 0; });
        if (!flagged.length) {
          pagesWithIssues.innerHTML = '<p class="text-sm" style="color: var(--text-tertiary);">No scanned pages have outstanding Analytics findings.</p>';
        } else {
          // List each page's findings (title + severity), not just a count.
          pagesWithIssues.innerHTML = '<ul class="text-sm" style="margin:0; padding-left: 1.2em;">' +
            flagged.map(function (p) {
              var pFindings = p.findings || [];
              var n = pFindings.length;
              var sub = '<ul style="margin:2px 0 0; padding-left: 1.2em; list-style: none;">' +
                pFindings.map(function (f) {
                  var isCritical = f.severity === 'critical';
                  var dotColor = isCritical ? 'var(--color-fail, #dc2626)' : 'var(--color-warn, #d97706)';
                  return '<li style="margin-bottom:2px; color: var(--text-secondary);">' +
                    '<span style="display:inline-block; width:6px; height:6px; border-radius:50%; ' +
                    'background:' + dotColor + '; margin-right:6px;"></span>' +
                    U.escapeHtml(f.title || 'Untitled finding') + '</li>';
                }).join('') +
                '</ul>';
              return '<li style="margin-bottom:10px; word-break:break-all;">' + U.escapeHtml(p.url || '') +
                ' <span style="color: var(--text-tertiary);">— ' + n + ' finding' + (n === 1 ? '' : 's') + '</span>' +
                sub + '</li>';
            }).join('') +
            '</ul>';
        }
      }
    }


    /* Email history */

    function loadEmailHistory() {
      var list = document.getElementById('emailHistoryList');
      if (!list) return;

      window.Api.reports.getEmailHistory(auditId).then(function (history) {
        if (!history.length) {
          list.innerHTML = '<p class="email-empty">No emails sent for this report yet.</p>';
          return;
        }
        list.innerHTML = history.map(function (h) {
          var statusClass = h.status === 'sent' ? 'badge--success' : 'badge--error';
          var statusLabel = h.status === 'sent' ? 'Sent' : 'Failed';
          // EmailHistoryOut exposes recipient_to / recipient_cc (camelCased by api.js).
          var recipientsText = (h.recipientTo || []).join(', ');
          var ccCount = (h.recipientCc || []).length;
          return '<div class="issue-row">' +
            '<div class="issue-row__body">' +
              '<div class="issue-row__title">' + esc(recipientsText) + (ccCount ? ' <span class="text-tertiary">+' + ccCount + ' CC</span>' : '') + '</div>' +
              '<div class="issue-row__desc">' + esc(h.subject || '') +
                (h.status !== 'sent' && h.errorMessage ? ' — ' + esc(h.errorMessage) : '') +
                ' · ' + U.formatRelativeTime(new Date(h.sentAt).getTime()) +
              '</div>' +
            '</div>' +
            '<span class="issue-row__sev badge ' + statusClass + '">' + statusLabel + '</span>' +
          '</div>';
        }).join('');
      }).catch(function () {
        list.innerHTML = '<p class="email-empty">Couldn’t load the email history right now.</p>';
      });
    }
  });
})();
