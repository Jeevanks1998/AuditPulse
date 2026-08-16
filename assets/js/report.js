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
    seo: 'seoCheckGrid',
    performance: 'performanceCheckGrid',
    accessibility: 'accessibilityCheckGrid',
    security: 'securityCheckGrid'
  };
  var MODULE_SCORE_CHIP_IDS = {
    seo: 'seoScoreChip',
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
    seo: 'SEO', performance: 'Performance', accessibility: 'Accessibility',
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

  document.addEventListener('DOMContentLoaded', function () {
    var scoreGrid = document.getElementById('scoreGrid');
    if (!scoreGrid) return; // not on report.html

    var auditId = U.getQueryParam('id');
    var shareBtn = document.getElementById('shareReportBtn');
    var printBtn = document.getElementById('printReportBtn');
    var downloadBtn = document.getElementById('downloadPdfBtn');
    var evidenceBtn = document.getElementById('downloadEvidenceBtn');
    var sendToPocBtn = document.getElementById('sendToPocBtn');

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
    });

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

      if (favicon) favicon.textContent = U.faviconLetter(report.url);
      if (urlEl) urlEl.textContent = host;
      if (metaEl) metaEl.textContent = 'Completed ' + U.formatRelativeTime(new Date(report.generatedAt).getTime());
      if (label) label.innerHTML = report.overall + '<small>Score</small>';
      if (ring) U.setRingBand(ring, report.overall);
      if (circle) U.setRingProgress(circle, report.overall);
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
        function jump() { section.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
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

      list.innerHTML = groups.map(function (g) {
        var affects = g.count > 1 ? (g.count + ' items') : '1 item';
        return (
          '<div class="issue-row">' +
            '<span class="issue-row__icon">' + FAIL_ICON + '</span>' +
            '<div class="issue-row__body">' +
              '<div class="issue-row__title">' + findingIdBadge(g.finding_id) + U.escapeHtml(g.title) + '</div>' +
              '<div class="issue-row__desc">' + U.escapeHtml(moduleLabel(g.module)) + ' &middot; ' + U.escapeHtml(g.description || '') + '</div>' +
            '</div>' +
            '<span class="issue-row__sev badge badge--error">' + U.escapeHtml(affects) + '</span>' +
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

      list.innerHTML = items.map(function (item) {
        var sevClass = item.severity === 'critical' ? 'badge--error' : (item.severity === 'warning' ? 'badge--warning' : 'badge--neutral');
        var fid = findingByTitle[item.title];
        return (
          '<div class="issue-row">' +
            '<span class="issue-row__sev badge ' + sevClass + '" style="flex-shrink:0;">' + U.escapeHtml((item.severity || '').toUpperCase()) + '</span>' +
            '<div class="issue-row__body">' +
              '<div class="issue-row__title">' + findingIdBadge(fid) + U.escapeHtml(item.title) +
                '<span style="color: var(--text-tertiary); font-weight:400;"> &middot; ' + U.escapeHtml(item.affected_area || '') + '</span></div>' +
              '<div class="issue-row__desc">' + U.escapeHtml(item.impact || '') + '</div>' +
            '</div>' +
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
        if (chip && scoreByModule[module] != null) chip.textContent = scoreByModule[module] + ' / 100';
      });

      Object.keys(MODULE_CHECK_GRID_IDS).forEach(function (module) {
        var findingsForModule = report.findings.filter(function (f) { return f.module === module; });
        renderCheckGrid(MODULE_CHECK_GRID_IDS[module], findingsForModule);
      });
    }

    function renderConsent(consent) {
      var chip = document.getElementById('consentScoreChip');
      var checkGrid = document.getElementById('consentCheckGrid');
      var shotWrap = document.getElementById('consentScreenshotWrap');

      if (!consent) {
        if (chip) chip.textContent = 'Not scanned';
        if (checkGrid) checkGrid.innerHTML = '<p class="text-sm" style="color: var(--text-tertiary);">This audit didn\'t include the consent module.</p>';
        if (shotWrap) shotWrap.innerHTML = '';
        return;
      }

      if (chip) chip.textContent = consent.consentScore + ' / 100';

      if (checkGrid) {
        var items = [
          { label: 'Cookie banner detected', ok: consent.hasCookieBanner },
          { label: 'Blocks trackers before consent', ok: consent.bannerBlocksScriptsPreConsent },
          { label: 'GDPR-compliant', ok: consent.gdprCompliant },
          { label: 'CCPA-compliant', ok: consent.ccpaCompliant }
        ];
        // consent.runtime.run_consent_runtime's actual click-through verdicts
        // (§4.2/§4.3) — only shown once the runtime pass ran, since a null
        // verdict means "not tested", never a silent pass.
        if (consent.runtimeTested) {
          var rr = consent.runtimeResult || {};
          items.push({ label: 'Reject blocks tracking', ok: !!rr.reject_blocks_tracking, tested: rr.reject_blocks_tracking !== null && rr.reject_blocks_tracking !== undefined });
          items.push({ label: 'Accept allows tracking', ok: !!rr.accept_allows_tracking, tested: rr.accept_allows_tracking !== null && rr.accept_allows_tracking !== undefined });
          items.push({ label: 'Personalize exposes controls', ok: !!rr.personalize_exposes_controls, tested: rr.personalize_exposes_controls !== null && rr.personalize_exposes_controls !== undefined });
        }
        checkGrid.innerHTML = items.map(function (item) {
          var tested = item.tested !== false;
          var cls = !tested ? 'check-item--pending' : (item.ok ? 'check-item--pass' : 'check-item--fail');
          var icon = !tested ? '' : (item.ok ? PASS_ICON : FAIL_ICON);
          return '<div class="check-item ' + cls + '"><span class="check-item__icon">' + icon + '</span><span class="check-item__label">' + U.escapeHtml(item.label) + (tested ? '' : ' (not tested)') + '</span></div>';
        }).join('');
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
                  '<img src="' + U.escapeHtml(s.url) + '" alt="' + U.escapeHtml(s.label) + ' screenshot" style="width:100%; height:160px; object-fit:contain; border-radius: var(--radius-md);">' +
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

    function renderAnalytics(analytics) {
      var chip = document.getElementById('analyticsScoreChip');
      var checkGrid = document.getElementById('analyticsCheckGrid');
      var configTable = document.getElementById('analyticsConfigTable');
      var vendorTable = document.getElementById('analyticsVendorTable');
      var eventValidation = document.getElementById('analyticsEventValidation');
      var detail = document.getElementById('analyticsDetail');
      var fullSite = document.getElementById('analyticsFullSite');

      if (!analytics) {
        if (chip) chip.style.display = 'none';
        if (checkGrid) checkGrid.innerHTML = '<p class="text-sm" style="color: var(--text-tertiary);">This audit didn\'t include the analytics module.</p>';
        if (configTable) configTable.innerHTML = '';
        if (vendorTable) vendorTable.innerHTML = '';
        if (eventValidation) eventValidation.innerHTML = '';
        if (detail) detail.textContent = '';
        if (fullSite) fullSite.style.display = 'none';
        return;
      }

      if (chip) { chip.style.display = ''; chip.textContent = analytics.analyticsScore + ' / 100'; }

      if (checkGrid) {
        var items = [
          { label: 'Any tracker detected', ok: (analytics.trackersDetected || []).length > 0 },
          { label: 'Tag Manager detected', ok: analytics.tagManagerDetected },
          { label: 'Data layer present', ok: analytics.dataLayerPresent },
          { label: 'Runtime-validated', ok: !!analytics.runtimeAvailable, tested: !!analytics.runtimeTested }
        ];
        checkGrid.innerHTML = items.map(function (item) {
          var tested = item.tested !== false;
          var cls = !tested ? 'check-item--pending' : (item.ok ? 'check-item--pass' : 'check-item--fail');
          var icon = !tested ? '' : (item.ok ? PASS_ICON : FAIL_ICON);
          return '<div class="check-item ' + cls + '"><span class="check-item__icon">' + icon + '</span><span class="check-item__label">' + U.escapeHtml(item.label) + (tested ? '' : ' (not tested)') + '</span></div>';
        }).join('');
      }

      // vendor_configs only contains keys for vendors actually detected —
      // this is the single source of truth for both the Configuration
      // section and which rows the Detection & Runtime table shows.
      var vendorConfigs = analytics.vendorConfigs || {};
      var detectedKeys = Object.keys(vendorConfigs);
      var runtimeVendors = (analytics.runtimeResult && analytics.runtimeResult.vendors) || {};

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

      // Analytics Event Validation (§1.3) — actual runtime evidence only;
      // empty (not a "failed" table) when the runtime pass never ran.
      if (eventValidation) {
        var runtimeKeys = Object.keys(runtimeVendors);
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
                '<td style="padding:6px 10px;">' + pFindings.length + '</td>' +
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
          pagesWithIssues.innerHTML = '<ul class="text-sm" style="margin:0; padding-left: 1.2em;">' +
            flagged.map(function (p) {
              var n = (p.findings || []).length;
              return '<li style="margin-bottom:4px; word-break:break-all;">' + U.escapeHtml(p.url || '') +
                ' <span style="color: var(--text-tertiary);">— ' + n + ' finding' + (n === 1 ? '' : 's') + '</span></li>';
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
