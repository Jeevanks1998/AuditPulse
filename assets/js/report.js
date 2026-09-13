/* ==========================================================================
   report.js — report.html page logic. Reads ?id=<auditId> from the URL,
   fetches that audit's real report from the backend (see assets/js/api.js
   Api.reports), and renders the banner, score grid, critical issues, AI
   recommendations, per-module score chips/findings, and the consent-banner
   screenshot from it. Also wires the share / print / download-PDF actions
   to the real backend endpoints.
   ========================================================================== */

(function () {
  var U = window.Utils;

  var PASS_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4L19 7"/></svg>';
  var FAIL_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>';
  var WARN_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>';

  // report.html section ids that findings/score-grid modules can actually
  // map to. Modules the backend computes but this page has no section for
  // (ux, images, links, mobile, forms) still show up in the score grid,
  // they just won't be clickable-to-scroll or get a detail section.
  var MODULE_CHECK_GRID_IDS = {
    performance: 'performanceCheckGrid',
    accessibility: 'accessibilityCheckGrid',
    security: 'securityCheckGrid'
  };
  // Mirrors backend consent.consent_score.GDPR_CHECK_ORDER / GDPR_CHECK_LABELS —
  // keep the key list and order in sync with that module. `severity` /
  // `failReason` are display-only (not persisted anywhere) — they drive
  // the "Why?" failure explanation in renderConsent below, derived
  // straight from these same checks rather than a separate issue list.
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
    { key: 'reject_blocks_tracking', label: 'Reject actually blocks tracking', severity: 'critical',
      failReason: 'Reject does not actually stop tracking' }
  ];

  // Mirrors backend consent.consent_score.CCPA_CHECK_ORDER / CCPA_CHECK_LABELS.
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
    { key: 'opt_out_behavior_verified', label: 'Opt-out actually stops tracking', severity: 'critical',
      failReason: 'Opt-out does not actually stop tracking' }
  ];

  var MODULE_SCORE_CHIP_IDS = {
    performance: 'performanceScoreChip',
    accessibility: 'accessibilityScoreChip',
    security: 'securityScoreChip'
  };

  // Module label + "Healthy/Needs Attention/Issues Found" status wording,
  // mirroring backend/reports/generator.py's MODULE_LABELS /
  // OVERALL_STATUS_LABELS exactly (§3.3/§3.4/§11) so the on-screen Overall
  // Status and module names never drift from what the PDF prints for the
  // same audit.
  var MODULE_LABELS = {
    performance: 'Performance', accessibility: 'Accessibility',
    security: 'Security', ux: 'UX', images: 'Images', links: 'Links',
    mobile: 'Mobile', forms: 'Forms', consent: 'Consent', analytics: 'Analytics', ai: 'AI Review'
  };
  var OVERALL_STATUS_LABELS = { good: 'Healthy', mid: 'Needs Attention', bad: 'Issues Found' };
  var MAX_KEY_AREAS = 6;

  /* ------------------------- shared report-derived helpers ------------------------- */
  // These mirror reports/generator.py's count_by_severity / weakest_module /
  // score_band + OVERALL_STATUS_LABELS and pdf/summary.py's _group_findings —
  // computed client-side from the same real `report.findings` /
  // `report.scoreGrid` the export.json endpoint returns, so the numbers
  // shown here can never drift from what the PDF (built from the identical
  // payload) shows for the same audit (§9/§11 "No Dummy Data Rule").

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

  // Collapses findings/steps that share the same (title, module) into one
  // group with an affected-item count — mirrors pdf/summary.py's
  // _group_findings and pdf/recommendations.py's _group_steps (§3.6/§3.8:
  // "Do not repeat the same contrast recommendation for every selector;
  // group the recommendation and show the affected selectors/count
  // separately"), so a duplicated finding shows up once here too.
  function groupByTitleModule(items) {
    var order = [];
    var byKey = {};
    (items || []).forEach(function (item) {
      var key = (item.title || '') + '\u0000' + (item.module || '');
      if (!byKey[key]) {
        byKey[key] = { title: item.title || '', module: item.module || '', description: item.description || '',
          finding_id: item.finding_id || '', severity: item.severity || 'info', step: item.step || '', count: 0 };
        order.push(key);
      }
      byKey[key].count += 1;
    });
    return order.map(function (key) { return byKey[key]; });
  }

  function findingIdBadge(id) {
    return id ? '<span class="finding-id-badge">' + U.escapeHtml(id) + '</span> ' : '';
  }

  /* ------------------------- Module Details accordion (Phase 9) -------------------------
     The five module sections (#performance/#accessibility/#analytics/#consent/#security)
     are native <details>/<summary> elements. Native <details> already handles plain
     open/close and (in every current browser) auto-opens on direct #hash navigation —
     this just adds the two things the browser can't do on its own: opening the right
     module when a score-grid card is clicked (a scrollIntoView call, not a real
     navigation, so it doesn't trigger the browser's fragment-in-<details> behavior),
     and forcing every module open before printing/PDF export so the printed output
     always shows everything regardless of what's expanded on screen. */

  function openModuleAccordion(id) {
    var el = id && document.getElementById(id);
    if (el && el.tagName === 'DETAILS' && !el.open) el.open = true;
    return el;
  }

  function wireModuleAccordions() {
    // Includes .analytics-subsection so the nested Analytics groups (§Phase
    // 10) are force-opened for print/PDF export the same way the top-level
    // module accordions are — otherwise a collapsed sub-section would be
    // silently missing from the printed report.
    var accordions = U.qsa('.module-accordion, .analytics-subsection');
    if (!accordions.length) return;

    // Sidebar "Audit Modules" links point at #performance etc. — open the
    // target accordion on click so it's expanded by the time the browser
    // scrolls to it (belt-and-braces alongside the native auto-open).
    U.qsa('a[href^="#"]').forEach(function (link) {
      var id = link.getAttribute('href').slice(1);
      if (document.getElementById(id)) U.on(link, 'click', function () { openModuleAccordion(id); });
    });

    // Deep link support, e.g. report.html?id=123#security
    if (location.hash) openModuleAccordion(location.hash.slice(1));
    U.on(window, 'hashchange', function () { openModuleAccordion(location.hash.slice(1)); });

    // beforeprint forces every module open so printed/PDF output shows
    // everything regardless of what's expanded on screen; afterprint puts
    // back whatever was actually open beforehand.
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
    });
  }

  // Colors a module's score chip (score-chip--good/mid/bad, same modifier
  // classes the rest of the app uses) and sets its accordion status icon
  // to match — mirrors U.scoreBand so the icon can never disagree with
  // the number sitting right next to it.
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

  document.addEventListener('DOMContentLoaded', function () {
    var scoreGrid = document.getElementById('scoreGrid');
    if (!scoreGrid) return; // not on report.html

    var auditId = U.getQueryParam('id');
    var shareBtn = document.getElementById('shareReportBtn');
    var printBtn = document.getElementById('printReportBtn');
    var downloadBtn = document.getElementById('downloadPdfBtn');
    var evidenceBtn = document.getElementById('downloadEvidenceBtn');
    var sendToPocBtn = document.getElementById('sendToPocBtn');

    // Wired unconditionally (before the auditId guard below) so the
    // module accordions — sidebar deep-links, print-all-open — still
    // work even if there's no report to load yet.
    wireModuleAccordions();

    if (!auditId) {
      window.Notifications.error('No report selected', 'Open a report from your dashboard or history so we know which audit to show.');
      return;
    }

    var currentReport = null; // populated once the fetch below resolves

    /* ------------------------------ banner actions ------------------------------ */

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

    U.on(sendToPocBtn, 'click', function () {
      openSendToPocModal();
      closeMoreMenu();
    });

    /* ------------------------------ "More" dropdown ------------------------------
       Holds Print / Evidence ZIP / Send to POC — same buttons, same handlers,
       just tucked away so the banner isn't five buttons wide (Phase 1). */
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

    // Print/Evidence handlers below already close nothing on their own since
    // they don't navigate away — close the menu once the action is triggered.
    U.on(printBtn, 'click', closeMoreMenu);
    U.on(evidenceBtn, 'click', closeMoreMenu);

    U.on(document, 'click', function (e) {
      if (moreDropdown && !moreDropdown.contains(e.target)) closeMoreMenu();
    });
    U.on(document, 'keydown', function (e) {
      if (e.key === 'Escape') closeMoreMenu();
    });

    /* ------------------------------ Ask AI ------------------------------
       Free-text Q&A grounded in this audit (POST /ai/{auditId}/chat).
       chatHistory accumulates { question, answer } turns and is sent back
       each time so the backend has multi-turn context. */
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

    /* --------------------------- fetch + render --------------------------- */

    Promise.all([
      window.Api.reports.getFull(auditId).catch(function () {
        // The AI-enriched export can be slower / can fail if the AI layer
        // errors; fall back to the plain (score grid + findings) report
        // rather than showing nothing.
        return window.Api.reports.get(auditId);
      }),
      window.Api.audits.getConsent(auditId).catch(function () { return null; }),
      window.Api.audits.getAnalytics(auditId).catch(function () { return null; })
    ]).then(function (results) {
      currentReport = results[0];
      renderBanner(currentReport);
      renderExecutiveSummary(currentReport);
      renderScoreGrid(currentReport);
      renderSeverityDistribution(currentReport);
      renderCriticalFindings(currentReport);
      renderBusinessImpact(currentReport);
      renderActionPlanSection(currentReport);
      renderRecommendations(currentReport);
      renderModuleSections(currentReport);
      renderConsent(results[1]);
      renderAnalytics(results[2]);
      document.title = 'Audit Report — ' + U.hostnameOf(currentReport.url) + ' — AuditPulse';
      loadEmailHistory();
    }).catch(function (err) {
      window.Notifications.error('Couldn\'t load report', err.message || 'This report may not exist or may still be running.');
    });

    /* ------------------------------- renderers ------------------------------- */

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
      if (metaEl) metaEl.textContent = 'Completed ' + U.formatRelativeTime(new Date(report.generatedAt).getTime());
      if (label) label.textContent = report.overall;
      if (ring) U.setRingBand(ring, report.overall);
      if (circle) U.setRingProgress(circle, report.overall);
      if (bandEl) {
        bandEl.textContent = overallStatusLabel(report.overall);
        bandEl.setAttribute('data-band', U.scoreBand(report.overall));
      }
    }

    function renderScoreGrid(report) {
      if (!scoreGrid || !window.Components) return;
      scoreGrid.innerHTML = report.scoreGrid.map(function (cell) {
        var target = (cell.targetSection || '').replace(/^section-/, '');
        return window.Components.renderScoreCard({ score: cell.score, label: cell.label, target: target });
      }).join('');

      // Re-wire score-cell -> section scroll + radar chart now that the
      // grid has been rebuilt (report.js used to do this once on load
      // against static markup; now it has to happen after each render).
      var cells = U.qsa('.score-cell', scoreGrid);
      var labels = [];
      var values = [];
      cells.forEach(function (cell) {
        var labelEl = cell.querySelector('.score-cell__label');
        var valueEl = cell.querySelector('.vring__label');
        if (labelEl && valueEl) {
          labels.push(labelEl.textContent.trim());
          values.push(parseInt(valueEl.textContent, 10) || 0);
        }
        var target = cell.dataset.target;
        var section = target && document.getElementById(target);
        if (!section) return;
        function jump() {
          if (section.tagName === 'DETAILS') section.open = true;
          section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        U.on(cell, 'click', jump);
        U.on(cell, 'keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); jump(); }
        });
      });

      var radarCanvas = document.getElementById('radarChart');
      if (radarCanvas && window.Charts && labels.length) {
        window.Charts.renderRadar('radarChart', labels, values, { datasetLabel: 'Score' });
      }
    }

    /* --------------------- Executive Summary (§3.3) --------------------- */

    function renderExecutiveSummary(report) {
      var textEl = document.getElementById('execSummaryText');
      var statusBadge = document.getElementById('overallStatusBadge');
      var cardGrid = document.getElementById('metricCardGrid');
      var keyAreasCard = document.getElementById('keyAreasCard');
      var keyAreasList = document.getElementById('keyAreasList');

      if (textEl) {
        textEl.textContent = report.executiveSummary || '';
        textEl.style.display = report.executiveSummary ? '' : 'none';
      }

      var counts = severityCounts(report.findings);
      var totalCount = (report.findings || []).length;
      var weakest = weakestModule(report.scoreGrid);
      var status = overallStatusLabel(report.overall);
      var band = U.scoreBand(report.overall);

      if (statusBadge) {
        statusBadge.textContent = 'Overall Status: ' + status;
        statusBadge.className = 'badge ' + (band === 'good' ? 'badge--success' : (band === 'mid' ? 'badge--warning' : 'badge--error'));
      }

      if (cardGrid) {
        var cards = [
          { label: 'Overall Score', value: report.overall + '/100' },
          { label: 'Critical Findings', value: String(counts.critical) },
          { label: 'Total Findings', value: String(totalCount) },
          { label: 'Weakest Module', value: weakest ? (weakest.label + ' (' + weakest.score + '/100)') : 'N/A' }
        ];
        cardGrid.innerHTML = cards.map(function (c) {
          return '<div class="metric-card">' +
            '<div class="metric-card__value">' + U.escapeHtml(c.value) + '</div>' +
            '<div class="metric-card__label">' + U.escapeHtml(c.label) + '</div>' +
          '</div>';
        }).join('');
      }

      // "Key Areas Requiring Attention" — the real critical/warning findings,
      // grouped so a repeated issue (e.g. five contrast failures) contributes
      // one line instead of five (mirrors pdf/summary.py's _render_key_areas).
      var notable = (report.findings || []).filter(function (f) { return f.severity === 'critical' || f.severity === 'warning'; });
      var groups = groupByTitleModule(notable).slice(0, MAX_KEY_AREAS);
      if (keyAreasCard && keyAreasList) {
        if (!groups.length) {
          keyAreasCard.style.display = 'none';
        } else {
          keyAreasCard.style.display = '';
          keyAreasList.innerHTML = groups.map(function (g) {
            var suffix = g.count > 1 ? ' (' + g.count + ' instances)' : '';
            return '<li><b>' + U.escapeHtml(g.title) + '</b> — ' + U.escapeHtml(moduleLabel(g.module)) + U.escapeHtml(suffix) + '</li>';
          }).join('');
        }
      }
    }

    /* ----------------- Finding Severity Distribution (§3.5) ----------------- */

    function renderSeverityDistribution(report) {
      var table = document.getElementById('severityTable');
      var counts = severityCounts(report.findings);

      if (window.Charts && document.getElementById('severityChart')) {
        window.Charts.renderSeverityDoughnut('severityChart', { high: counts.critical, medium: counts.warning, low: counts.info }, { showLegend: false });
      }

      if (table) {
        var rows = [
          { label: 'Critical', count: counts.critical, cls: 'badge--error' },
          { label: 'Warning', count: counts.warning, cls: 'badge--warning' },
          { label: 'Info', count: counts.info, cls: 'badge--neutral' }
        ];
        table.innerHTML = rows.map(function (r) {
          return '<div class="severity-dist__row">' +
            '<span class="badge ' + r.cls + '">' + r.label + '</span>' +
            '<span class="severity-dist__count">' + r.count + '</span>' +
          '</div>';
        }).join('');
      }
    }

    /* --------------------------- Critical Findings (§3.6) --------------------------- */

    function renderCriticalFindings(report) {
      var list = document.getElementById('criticalFindingsList');
      var badge = document.getElementById('criticalFindingsBadge');
      if (!list) return;

      var critical = (report.findings || []).filter(function (f) { return f.severity === 'critical'; });
      var groups = groupByTitleModule(critical);

      if (badge) {
        badge.textContent = critical.length !== groups.length
          ? (critical.length + ' grouped into ' + groups.length)
          : (critical.length + ' open');
      }

      if (!groups.length) {
        list.innerHTML = '<div class="issue-row"><div class="issue-row__body"><div class="issue-row__title">No critical findings</div><div class="issue-row__desc">Nothing critical-severity was found in this audit.</div></div></div>';
        return;
      }

      // Each finding is a scannable, stacked card: a CRITICAL severity badge
      // (the only place severity color is used) + Finding ID up top, then
      // title, module/instance-count, description, and a "View details"
      // link that jumps to that module's detailed check section below.
      list.innerHTML = groups.map(function (g) {
        var moduleText = moduleLabel(g.module) + (g.count > 1 ? ' \u00b7 ' + g.count + ' instances' : '');
        var link = g.module
          ? '<div class="issue-row__footer"><a class="issue-row__link" href="#' + U.escapeHtml(g.module) + '">View details \u2192</a></div>'
          : '';
        return (
          '<div class="issue-row issue-row--finding">' +
            '<div class="issue-row__top">' +
              '<span class="badge badge--error issue-row__sevbadge">Critical</span>' +
              findingIdBadge(g.finding_id) +
            '</div>' +
            '<div class="issue-row__title">' + U.escapeHtml(g.title) + '</div>' +
            '<div class="issue-row__module">' + U.escapeHtml(moduleText) + '</div>' +
            (g.description ? '<div class="issue-row__desc">' + U.escapeHtml(g.description) + '</div>' : '') +
            link +
          '</div>'
        );
      }).join('');
    }

    /* ------------------------------ Business Impact (§3.7) ------------------------------ */

    function renderBusinessImpact(report) {
      var card = document.getElementById('businessImpactCard');
      var list = document.getElementById('businessImpactList');
      if (!card || !list) return;

      var items = report.businessImpact || [];
      if (!items.length) {
        card.style.display = 'none';
        return;
      }
      card.style.display = '';

      // Cross-reference each item back to the real Finding ID that produced
      // it (same (title, module) natural key pdf/recommendations.py uses),
      // rather than inventing one here.
      var findingByTitle = {};
      (report.findings || []).forEach(function (f) {
        if (!(f.title in findingByTitle)) findingByTitle[f.title] = f.finding_id;
      });

      // Executive-friendly framing: each item becomes its own labeled card —
      // "Business Risk" (what/where, from the same generated title +
      // affected_area) above "Potential impact" (the plain-English
      // consequence) — instead of one dense generic list, so a manager can
      // read the risk and its cost without the technical finding detail.
      list.innerHTML = items.map(function (item) {
        var sevClass = item.severity === 'critical' ? 'badge--error' : (item.severity === 'warning' ? 'badge--warning' : 'badge--neutral');
        var fid = findingByTitle[item.title];
        return (
          '<div class="impact-card">' +
            '<div class="impact-card__section-label">Business Risk</div>' +
            '<div class="impact-card__risk">' +
              '<span class="badge ' + sevClass + '">' + U.escapeHtml((item.severity || '').toUpperCase()) + '</span>' +
              findingIdBadge(fid) + U.escapeHtml(item.title) +
              (item.affected_area ? '<span class="impact-card__area">' + U.escapeHtml(item.affected_area) + '</span>' : '') +
            '</div>' +
            '<div class="impact-card__section-label">Potential impact</div>' +
            '<div class="impact-card__impact-text">' + U.escapeHtml(item.impact || '') + '</div>' +
          '</div>'
        );
      }).join('');
    }

    /* --------------------------------- Action Plan (§3.8) --------------------------------- */

    var ACTION_PLAN_HORIZONS = [
      { key: 'quickWins', title: 'Phase 1 \u2013 Immediate / High Priority Actions' },
      { key: 'shortTerm', title: 'Phase 2 \u2013 Short-Term Actions' },
      { key: 'longTerm', title: 'Phase 3 \u2013 Optimization Actions' }
    ];

    function renderActionPlanSection(report) {
      var container = document.getElementById('actionPlanPhases');
      if (!container) return;

      var plan = report.actionPlan;
      if (!plan) {
        container.innerHTML = '';
        return;
      }

      var findingByKey = {};
      (report.findings || []).forEach(function (f) {
        findingByKey[(f.title || '') + '\u0000' + (f.module || '')] = f.finding_id;
        if (!(('\u0000title\u0000' + f.title) in findingByKey)) findingByKey['\u0000title\u0000' + f.title] = f.finding_id;
      });
      function lookupFindingId(title, module) {
        return findingByKey[(title || '') + '\u0000' + (module || '')] || findingByKey['\u0000title\u0000' + title] || '';
      }

      var html = ACTION_PLAN_HORIZONS.map(function (horizon) {
        var steps = plan[horizon.key] || [];
        if (!steps.length) return '';
        var groups = groupByTitleModule(steps);
        var rows = groups.map(function (g) {
          var fid = lookupFindingId(g.title, g.module);
          var affects = g.count > 1 ? ('  <span style="color: var(--text-tertiary);">(affects ' + g.count + ' items)</span>') : '';
          return '<tr style="border-top:1px solid var(--border, #e5e7eb);">' +
            '<td style="padding:6px 10px;"><span class="badge badge--' + (g.severity === 'critical' ? 'error' : (g.severity === 'warning' ? 'warning' : 'neutral')) + '">' + U.escapeHtml((g.severity || '').replace(/^\w/, function (c) { return c.toUpperCase(); })) + '</span></td>' +
            '<td style="padding:6px 10px; color: var(--text-tertiary);">' + (fid ? U.escapeHtml(fid) : '&mdash;') + '</td>' +
            '<td style="padding:6px 10px; color: var(--text-tertiary);">' + U.escapeHtml(moduleLabel(g.module)) + '</td>' +
            '<td style="padding:6px 10px;"><b>' + U.escapeHtml(g.title) + '</b>: ' + U.escapeHtml(g.step) + affects + '</td>' +
          '</tr>';
        }).join('');

        return '<div class="card card__pad" style="margin-bottom: var(--sp-4);">' +
          '<div class="card__head"><h3>' + U.escapeHtml(horizon.title) + '</h3></div>' +
          '<div style="overflow-x:auto;"><table class="text-sm" style="width:100%; border-collapse:collapse;">' +
            '<thead><tr style="text-align:left; color: var(--text-tertiary);">' +
              '<th style="padding:6px 10px;">Priority</th><th style="padding:6px 10px;">Finding ID</th>' +
              '<th style="padding:6px 10px;">Module</th><th style="padding:6px 10px;">Recommended Action</th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '</div>';
      }).join('');

      container.innerHTML = html || '<p class="text-sm" style="color: var(--text-tertiary);">No action-plan items were generated for this audit.</p>';
    }

    function renderRecommendations(report) {
      var card = document.getElementById('aiRecoCard');
      var list = document.getElementById('recoList');
      if (!card || !list) return;
      if (!report.priorities || !report.priorities.length) {
        card.style.display = 'none';
        return;
      }
      card.style.display = '';
      list.innerHTML = report.priorities.slice(0, 6).map(function (p, i) {
        var impactClass = p.severity === 'critical' ? 'badge--success' : 'badge--warning';
        var impactLabel = p.severity === 'critical' ? 'High impact' : 'Medium impact';
        var num = String(i + 1).padStart(2, '0');
        return (
          '<div class="reco-item">' +
            '<span class="reco-item__num">' + num + '</span>' +
            '<div><div class="reco-item__title">' + U.escapeHtml(p.title) + '</div><div class="reco-item__desc">' + U.escapeHtml(p.description || '') + '</div></div>' +
            '<span class="reco-item__impact badge ' + impactClass + '">' + impactLabel + '</span>' +
          '</div>'
        );
      }).join('');
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

    function renderCheckItemRow(item) {
      var tested = item.tested !== false;
      var cls = !tested ? 'check-item--pending' : (item.ok ? 'check-item--pass' : 'check-item--fail');
      var icon = !tested ? '' : (item.ok ? PASS_ICON : FAIL_ICON);
      return '<div class="check-item ' + cls + '"><span class="check-item__icon">' + icon + '</span><span class="check-item__label">' + U.escapeHtml(item.label) + (tested ? '' : ' (not tested)') + '</span></div>';
    }

    // Renders one compliance roll-up (GDPR or CCPA) as a single
    // pass/fail row, plus — only when it failed — a "Why?" disclosure
    // listing the specific checks that failed. Derives the failure list
    // straight from `checksMap` (consent.gdprChecks / consent.ccpaChecks)
    // and the matching *_CHECK_ITEMS array above; no separate issue list
    // is built for this, per the backend's gdpr_checks/ccpa_checks being
    // the single source of truth for "what's missing".
    function renderComplianceSummary(label, compliant, checkItems, checksMap) {
      var failed = checkItems.filter(function (c) { return checksMap[c.key] === false; });

      var cls = compliant ? 'check-item--pass' : 'check-item--fail';
      var icon = compliant ? PASS_ICON : FAIL_ICON;
      var html = '<div class="check-item ' + cls + '"><span class="check-item__icon">' + icon + '</span>' +
        '<span class="check-item__label">' + U.escapeHtml(label) + ' \u2014 ' + (compliant ? 'Passed' : 'Failed') + '</span></div>';

      if (!compliant && failed.length) {
        html += '<details class="compliance-why" style="margin: 2px 0 10px 34px;">' +
          '<summary class="text-sm" style="color: var(--text-tertiary); cursor: pointer;">Why?</summary>' +
          '<ul style="margin: 6px 0 0; padding: 0; list-style: none;">' +
          failed.map(function (c) {
            var dot = c.severity === 'critical' ? '\ud83d\udd34' : '\ud83d\udfe0';
            return '<li class="text-sm" style="margin-bottom: 4px;">' + dot + ' ' + U.escapeHtml(c.failReason || c.label) + '</li>';
          }).join('') +
          '</ul></details>';
      }
      return html;
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

      if (!consent) {
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

      // Foundation checks (always shown at top)
      if (foundationGrid) {
        var foundationItems = [
          { label: 'Cookie banner detected', ok: consent.hasCookieBanner },
          { label: 'Blocks trackers before consent', ok: consent.bannerBlocksScriptsPreConsent }
        ];
        foundationGrid.innerHTML = foundationItems.map(renderCheckItemRow).join('');
      }

      // Runtime behavior checks (shown only if tested) — a null verdict
      // means "not tested", never a silent pass.
      if (runtimeWrap) {
        if (consent.runtimeTested) {
          runtimeWrap.style.display = '';
          if (runtimeGrid) {
            var rr = consent.runtimeResult || {};
            var runtimeItems = [
              { label: 'Reject blocks tracking', ok: !!rr.reject_blocks_tracking, tested: rr.reject_blocks_tracking !== null && rr.reject_blocks_tracking !== undefined },
              { label: 'Accept allows tracking', ok: !!rr.accept_allows_tracking, tested: rr.accept_allows_tracking !== null && rr.accept_allows_tracking !== undefined },
              { label: 'Personalize exposes controls', ok: !!rr.personalize_exposes_controls, tested: rr.personalize_exposes_controls !== null && rr.personalize_exposes_controls !== undefined }
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

      // GDPR compliance details
      if (gdprGrid && gdprSection) {
        var gdprChecks = consent.gdprChecks || {};
        var gdprCheckRows = GDPR_CHECK_ITEMS.map(function (item) {
          var passed = gdprChecks[item.key];
          var tested = passed !== null && passed !== undefined;
          return {
            label: item.label,
            ok: !!passed,
            tested: tested
          };
        });
        gdprGrid.innerHTML = renderComplianceSummary('GDPR', consent.gdprCompliant, GDPR_CHECK_ITEMS, gdprChecks) +
          gdprCheckRows.map(renderCheckItemRow).join('');
        gdprSection.style.display = '';
        // Set GDPR section status
        var gdprBand = consent.gdprCompliant ? 'good' : 'bad';
        setAnalyticsSectionStatus('consentGdprStatusIcon', gdprBand);
      }

      // CCPA compliance details
      if (ccpaGrid && ccpaSection) {
        var ccpaChecks = consent.ccpaChecks || {};
        var ccpaCheckRows = CCPA_CHECK_ITEMS.map(function (item) {
          var passed = ccpaChecks[item.key];
          var tested = passed !== null && passed !== undefined;
          return {
            label: item.label,
            ok: !!passed,
            tested: tested
          };
        });
        ccpaGrid.innerHTML = renderComplianceSummary('CCPA', consent.ccpaCompliant, CCPA_CHECK_ITEMS, ccpaChecks) +
          ccpaCheckRows.map(renderCheckItemRow).join('');
        ccpaSection.style.display = '';
        // Set CCPA section status
        var ccpaBand = consent.ccpaCompliant ? 'good' : 'bad';
        setAnalyticsSectionStatus('consentCcpaStatusIcon', ccpaBand);
      }

      if (shotWrap) {
        // Prefer the full runtime evidence set (initial banner, Personalize,
        // after Reject, after Accept — consent.runtime's four capture
        // points, §5) and fall back to the single static banner capture
        // when the runtime pass didn't run or wasn't available.
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

    // vendor_key -> display name, mirrors backend analytics.analytics_score.TRACKER_DISPLAY_NAMES.
    var VENDOR_LABELS = {
      ga4: 'Google Analytics 4', gtm: 'Google Tag Manager', adobe: 'Adobe Analytics',
      piano: 'Piano Analytics', clarity: 'Microsoft Clarity', hotjar: 'Hotjar',
      meta_pixel: 'Meta Pixel', linkedin: 'LinkedIn Insight Tag', tiktok: 'TikTok Pixel'
    };

    function analyticsStatusBadge(status) {
      if (status === 'passed') return '<span style="color: var(--success, #16a34a);">Passed</span>';
      if (status === 'failed') return '<span style="color: var(--danger, #dc2626);">Failed</span>';
      if (status === 'not_applicable') return '<span style="color: var(--text-tertiary);">—</span>';
      return '<span style="color: var(--text-tertiary);">Not tested</span>';
    }

    // Sets one of the small sub-section status icons (Configuration,
    // Detection & Runtime, Event Validation, Coverage) — same good/mid/bad
    // banding and icon set as setModuleStatus, just reused at the
    // sub-section scale so a reader can judge each collapsed row without
    // opening it.
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

      // Overall Analytics Status — mirrors OVERALL_STATUS_LABELS off the
      // same score band the chip above already shows, so the headline
      // verdict can never disagree with the number sitting next to it.
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
          // tested = was the environment even capable of running runtime
          // validation (runtimeAvailable); ok = did it actually complete
          // (runtimeTested). A capable environment that still didn't
          // validate is a real failure, not just "not tested".
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

      // vendor_configs only contains keys for vendors actually detected —
      // this is the single source of truth for both the Configuration
      // section and which rows the Detection & Runtime table shows.
      var vendorConfigs = analytics.vendorConfigs || {};
      var detectedKeys = Object.keys(vendorConfigs);
      var runtimeVendors = (analytics.runtimeResult && analytics.runtimeResult.vendors) || {};

      // Configuration status — good once at least one vendor is actually
      // detected on the page, bad when nothing was found at all.
      setAnalyticsSectionStatus('analyticsConfigStatusIcon', detectedKeys.length ? 'good' : 'bad');

      // Analytics Configuration (§1.3) — actual detected ID(s) per vendor,
      // never a value for a vendor the backend didn't detect.
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

      // Detection & Runtime (§1.3) — built from *both* static detection
      // (vendorConfigs, always present once a vendor is found in markup)
      // and runtime results (runtimeVendors, only present once the
      // runtime pass has run) so a detected-but-not-fired vendor stays
      // visible with a Failed/Not tested runtime column instead of
      // disappearing from the table entirely.
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
                  : (v ? analyticsStatusBadge(v.page_view_status) : '<span style="color: var(--danger, #dc2626);">Failed</span>');
                return '<tr style="border-top:1px solid var(--border, #e5e7eb);">' +
                  '<td style="padding:6px 10px;">' + U.escapeHtml(VENDOR_LABELS[k] || k) + '</td>' +
                  '<td style="padding:6px 10px;">' + PASS_ICON + '</td>' +
                  '<td style="padding:6px 10px;">' + runtimeCol + '</td>' +
                  '<td style="padding:6px 10px;">' + (v ? analyticsStatusBadge(v.page_view_status) : '<span style="color: var(--text-tertiary);">Not tested</span>') + '</td>' +
                  '<td style="padding:6px 10px;">' + (v ? analyticsStatusBadge(v.scroll_status) : '<span style="color: var(--text-tertiary);">Not tested</span>') + '</td>' +
                  '<td style="padding:6px 10px;">' + (v ? analyticsStatusBadge(v.click_status) : '<span style="color: var(--text-tertiary);">Not tested</span>') + '</td>' +
                '</tr>';
              }).join('') +
              '</tbody></table></div>';
        }
      }

      // Detection & Runtime status — mid when runtime validation wasn't
      // performed at all (nothing failed, it just wasn't checked), good
      // when every detected vendor's page view fired, mid when only some
      // did, bad when none did despite runtime having actually run.
      if (!analytics.runtimeAvailable) {
        setAnalyticsSectionStatus('analyticsDetectionStatusIcon', detectedKeys.length ? 'mid' : 'bad');
      } else {
        var firedCount = detectedKeys.filter(function (k) {
          return runtimeVendors[k] && runtimeVendors[k].page_view_status === 'passed';
        }).length;
        var detectionBand = !detectedKeys.length ? 'bad'
          : (firedCount === detectedKeys.length ? 'good' : (firedCount > 0 ? 'mid' : 'bad'));
        setAnalyticsSectionStatus('analyticsDetectionStatusIcon', detectionBand);
      }

      // Analytics Event Validation (§1.3) — actual runtime evidence only;
      // empty (not a "failed" table) when the runtime pass never ran.
      if (eventValidation) {
        var runtimeKeys = Object.keys(runtimeVendors);

        // Event Validation status — mid when runtime never ran (untested,
        // not failed), bad when it ran but captured nothing, mid when any
        // vendor shows a duplicate page view (a real but non-fatal data
        // problem), good otherwise.
        if (!analytics.runtimeAvailable) {
          setAnalyticsSectionStatus('analyticsEventStatusIcon', 'mid');
        } else if (!runtimeKeys.length) {
          setAnalyticsSectionStatus('analyticsEventStatusIcon', 'bad');
        } else {
          var hasDuplicatePv = runtimeKeys.some(function (k) { return runtimeVendors[k].duplicate_page_view; });
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
                  '<td style="padding:6px 10px;">' + U.escapeHtml(v.vendor_name || VENDOR_LABELS[k] || k) + '</td>' +
                  '<td style="padding:6px 10px;">' + analyticsStatusBadge(v.custom_event_status) + '</td>' +
                  '<td style="padding:6px 10px;">' + (v.duplicate_page_view ? '<span style="color: var(--danger, #dc2626);">Yes</span>' : 'No') + '</td>' +
                  '<td style="padding:6px 10px;">' + (v.captured_request_count || 0) + '</td>' +
                  '<td style="padding:6px 10px;">' + U.escapeHtml((v.event_names || []).join(', ') || '—') + '</td>' +
                '</tr>';
              }).join('') +
              '</tbody></table></div>';
        }
      }

      if (detail) {
        var trackers = analytics.trackersDetected || [];
        detail.textContent = trackers.length
          ? 'Detected: ' + trackers.join(', ') + '.'
          : 'No analytics trackers detected on this page.';
      }

      renderAnalyticsFullSite(analytics);
    }

    /* --------------------------- Full-Site Analytics (§2.4 / §2.7) --------------------------- */
    // Site-level coverage, per-page results, cross-page consistency, and a
    // pages-with-issues list — all built from the API's actual page_results
    // / site_coverage / cross_page_findings (Phase 2.2/2.3/2.4), never
    // estimated client-side. Only rendered when the audit actually crawled
    // more than the homepage (page_results.length > 1); a homepage-only
    // audit leaves this section hidden rather than showing a redundant
    // single-page table underneath the Phase 1 sections above.

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

      // Coverage (§2.4) — every count here is the API's already-computed
      // site_coverage; nothing is derived or estimated in the browser.
      if (coverageGrid) {
        var coverageItems = [
          { label: 'Pages scanned', value: coverage.pages_scanned },
          { label: 'Pages with Analytics', value: coverage.pages_with_analytics },
          { label: 'Pages without Analytics', value: coverage.pages_without_analytics },
          { label: 'Pages with runtime failures', value: coverage.pages_with_runtime_failures },
          { label: 'Pages with inconsistencies', value: coverage.pages_with_analytics_inconsistencies },
          { label: 'Pages with findings', value: coverage.pages_with_findings }
        ];
        coverageGrid.innerHTML = coverageItems.map(function (item) {
          var val = (item.value === null || item.value === undefined) ? '—' : item.value;
          return '<div class="check-item"><span class="check-item__label">' + U.escapeHtml(item.label) +
            '</span><span style="font-weight:600;">' + val + '</span></div>';
        }).join('');
      }

      // Coverage status — good when every scanned page has Analytics with
      // no inconsistencies or runtime failures, mid when any of those
      // counts is above zero.
      var coverageHasIssue = !!(coverage.pages_without_analytics ||
        coverage.pages_with_analytics_inconsistencies ||
        coverage.pages_with_runtime_failures);
      setAnalyticsSectionStatus('analyticsCoverageStatusIcon', coverageHasIssue ? 'mid' : 'good');

      // Page-Level Analytics Results (§2.7) — actual URL, detected
      // trackers, score, and finding count for every page the crawler
      // actually scanned (analytics.analytics_score.PageAnalyticsResult).
      if (pageResultsTable) {
        pageResultsTable.innerHTML =
          '<div style="overflow-x:auto;">' +
          '<table class="text-sm" style="width:100%; border-collapse:collapse;">' +
            '<thead><tr style="text-align:left; color: var(--text-tertiary);">' +
              '<th style="padding:6px 10px;">Page</th><th style="padding:6px 10px;">Trackers Detected</th>' +
              '<th style="padding:6px 10px;">Score</th><th style="padding:6px 10px;">Findings</th>' +
            '</tr></thead><tbody>' +
            pageResults.map(function (p) {
              var pTrackers = p.trackers_detected || [];
              var pFindings = p.findings || [];
              return '<tr style="border-top:1px solid var(--border, #e5e7eb);">' +
                '<td style="padding:6px 10px; word-break:break-all;">' + U.escapeHtml(p.url || '') + '</td>' +
                '<td style="padding:6px 10px;">' + (pTrackers.length
                  ? U.escapeHtml(pTrackers.join(', '))
                  : '<span style="color: var(--text-tertiary);">None detected</span>') + '</td>' +
                '<td style="padding:6px 10px;">' + (p.score != null ? p.score : '—') + '</td>' +
                '<td style="padding:6px 10px;" title="' + U.escapeHtml(pFindings.map(function (f) { return f.title || ''; }).join('; ')) + '">' + pFindings.length + '</td>' +
              '</tr>';
            }).join('') +
            '</tbody></table></div>';
      }

      // Cross-Page Consistency (§2.3) — real discrepancies only; the
      // backend only ever produces these from >= 2 actually-scanned pages
      // with genuine evidence of a mismatch (a tracker missing from some
      // pages, or different IDs configured for the same vendor).
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
                var urls = f.affected_urls || [];
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

      // Pages With Analytics Issues — every scanned page carrying at
      // least one real (module=analytics) finding of its own, linked to
      // its actual URL so the list is directly actionable.
      if (pagesWithIssues) {
        var flagged = pageResults.filter(function (p) { return (p.findings || []).length > 0; });
        if (!flagged.length) {
          pagesWithIssues.innerHTML = '<p class="text-sm" style="color: var(--text-tertiary);">No scanned pages have outstanding Analytics findings.</p>';
        } else {
          // Each page now also lists what its finding(s) actually are —
          // title + severity per finding — instead of only a count, so
          // this list is actionable without cross-referencing another
          // table. Severity dot mirrors the check-item icon colors used
          // elsewhere in this file (critical=fail, warning/info=warn).
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

    /* --------------------------- Send to POC (§9) --------------------------- */

    function openSendToPocModal() {
      window.Api.reports.getAttachmentChoices().then(function (choices) {
        renderSendToPocModal(choices || {});
      }).catch(function () {
        // Falls back to the PDF-only default rather than blocking the modal
        // entirely if the choices endpoint is unreachable.
        renderSendToPocModal({ pdf: 'Audit Report PDF' });
      });
    }

    function renderSendToPocModal(choices) {
      var overlay = document.createElement('div');
      overlay.className = 'modal-overlay';
      overlay.style.cssText = 'position:fixed; inset:0; background:rgba(15,23,42,0.5); z-index:300; display:flex; align-items:center; justify-content:center; padding:20px;';

      var host = currentReport ? U.hostnameOf(currentReport.url) : '';
      var defaultSubject = 'Website Audit Report — ' + (currentReport ? currentReport.url : host);

      var attachmentRows = Object.keys(choices).map(function (key) {
        var checked = key === 'pdf' ? ' checked' : '';
        return '<label style="display:flex; align-items:center; gap:8px; padding:4px 0; font-size: var(--fs-sm);">' +
          '<input type="checkbox" name="attachment" value="' + U.escapeHtml(key) + '"' + checked + '>' +
          U.escapeHtml(choices[key]) +
        '</label>';
      }).join('');

      overlay.innerHTML =
        '<div class="modal-dialog" role="dialog" aria-modal="true" style="max-width:480px; background:var(--surface); border-radius:var(--radius-card); border:1px solid var(--border); box-shadow:var(--shadow-lg); padding:var(--sp-6); max-height:88vh; overflow-y:auto;">' +
          '<div class="modal-dialog__title" style="font-size:var(--fs-lg); font-weight:700; margin-bottom:12px;">Send Report to POC</div>' +
          '<div style="display:flex; flex-direction:column; gap:10px;">' +
            '<label style="font-size:var(--fs-sm); font-weight:600;">To <span style="font-weight:400; color:var(--text-tertiary);">(comma-separated)</span>' +
              '<input type="text" id="pocToInput" placeholder="jane@client.com, alex@client.com" style="width:100%; margin-top:4px;">' +
            '</label>' +
            '<label style="font-size:var(--fs-sm); font-weight:600;">CC <span style="font-weight:400; color:var(--text-tertiary);">(optional)</span>' +
              '<input type="text" id="pocCcInput" placeholder="cc@yourcompany.com" style="width:100%; margin-top:4px;">' +
            '</label>' +
            '<label style="font-size:var(--fs-sm); font-weight:600;">Subject' +
              '<input type="text" id="pocSubjectInput" value="' + U.escapeHtml(defaultSubject) + '" style="width:100%; margin-top:4px;">' +
            '</label>' +
            '<label style="font-size:var(--fs-sm); font-weight:600;">Message' +
              '<textarea id="pocBodyInput" rows="6" placeholder="Auto-generated from the report if left blank…" style="width:100%; margin-top:4px; font-family:inherit; resize:vertical;"></textarea>' +
            '</label>' +
            '<div>' +
              '<div style="font-size:var(--fs-sm); font-weight:600; margin-bottom:4px;">Attachments</div>' +
              attachmentRows +
            '</div>' +
          '</div>' +
          '<div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">' +
            '<button type="button" class="btn btn--secondary" id="pocCancelBtn">Cancel</button>' +
            '<button type="button" class="btn btn--primary" id="pocSendBtn">Send</button>' +
          '</div>' +
        '</div>';

      document.body.appendChild(overlay);
      document.body.style.overflow = 'hidden';

      function close() {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        document.body.style.overflow = '';
      }

      U.on(overlay, 'click', function (e) { if (e.target === overlay) close(); });
      U.on(overlay.querySelector('#pocCancelBtn'), 'click', close);

      var sendBtn = overlay.querySelector('#pocSendBtn');
      U.on(sendBtn, 'click', function () {
        var toRaw = overlay.querySelector('#pocToInput').value.trim();
        if (!toRaw) {
          window.Notifications.error('Recipient required', 'Enter at least one email address in the "To" field.');
          return;
        }
        var to = toRaw.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
        var ccRaw = overlay.querySelector('#pocCcInput').value.trim();
        var cc = ccRaw ? ccRaw.split(',').map(function (s) { return s.trim(); }).filter(Boolean) : [];
        var subject = overlay.querySelector('#pocSubjectInput').value.trim();
        var body = overlay.querySelector('#pocBodyInput').value.trim();
        var attachments = U.qsa('input[name="attachment"]:checked', overlay).map(function (el) { return el.value; });

        window.Loader.setButtonLoading(sendBtn, true, 'Sending…');
        window.Api.reports.sendToPoc(auditId, {
          to: to, cc: cc, subject: subject || undefined, body: body || undefined, attachments: attachments
        }).then(function (result) {
          if (result.success) {
            window.Notifications.success('Report sent', 'The audit report was emailed to ' + to.join(', ') + '.');
            close();
            loadEmailHistory();
          } else {
            window.Notifications.error('Send failed', result.errorMessage || 'The email could not be sent.');
          }
        }).catch(function (err) {
          window.Notifications.error('Send failed', err.message || 'The email could not be sent.');
        }).finally(function () {
          window.Loader.setButtonLoading(sendBtn, false);
        });
      });
    }

    /* --------------------------- Email History (§10) --------------------------- */

    function loadEmailHistory() {
      var card = document.getElementById('emailHistoryCard');
      var list = document.getElementById('emailHistoryList');
      if (!card || !list) return;

      window.Api.reports.getEmailHistory(auditId).then(function (history) {
        if (!history.length) {
          card.style.display = 'none';
          return;
        }
        card.style.display = '';
        list.innerHTML = history.map(function (h) {
          var statusClass = h.status === 'sent' ? 'badge--success' : 'badge--error';
          var statusLabel = h.status === 'sent' ? 'Sent' : 'Failed';
          return '<div class="issue-row">' +
            '<div class="issue-row__body">' +
              '<div class="issue-row__title">' + U.escapeHtml((h.to || []).join(', ')) + '</div>' +
              '<div class="issue-row__desc">' + U.escapeHtml(h.subject || '') +
                (h.status !== 'sent' && h.errorMessage ? ' — ' + U.escapeHtml(h.errorMessage) : '') +
                ' · ' + U.formatRelativeTime(new Date(h.sentAt).getTime()) +
              '</div>' +
            '</div>' +
            '<span class="issue-row__sev badge ' + statusClass + '">' + statusLabel + '</span>' +
          '</div>';
        }).join('');
      }).catch(function () {
        card.style.display = 'none';
      });
    }
  });
})();
