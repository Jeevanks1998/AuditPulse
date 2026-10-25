/* Dashboard page */

(function () {
  var U = window.Utils;

  // Keep in sync with GDPR_CHECK_ORDER in backend consent/consent_score.py (and report.js).
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

  // Keep in sync with CCPA_CHECK_ORDER in backend consent/consent_score.py (and report.js).
  var CCPA_CHECK_ITEMS = [
    { key: 'privacy_policy_available', label: 'Privacy policy available', severity: 'warning',
      failReason: 'Privacy policy was not detected' },
    { key: 'privacy_choices_link', label: '"Your Privacy Choices" link present', severity: 'warning',
      failReason: 'No "Your Privacy Choices" / California privacy rights link was found' },
    { key: 'do_not_sell_link', label: '"Do Not Sell or Share My Information" link present', severity: 'critical',
      failReason: 'No "Do Not Sell or Share My Information" link was found' },
    { key: 'opt_out_mechanism', label: 'Opt-out mechanism reachable', severity: 'critical',
      failReason: 'Opt-out mechanism not detected' },
    { key: 'gpc_honored', label: 'Global Privacy Control (GPC) signal handling detected', severity: 'warning',
      failReason: 'GPC handling not verified' },
    { key: 'opt_out_behavior_verified', label: 'Opt-out actually stops tracking', severity: 'critical',
      failReason: 'Opt-out does not actually stop tracking' }
  ];

  document.addEventListener('DOMContentLoaded', function () {
    var statJourney = document.getElementById('statJourney');
    if (!statJourney || !window.Api) return; // not on the dashboard

    var statCritical = document.getElementById('statCriticalIssues');
    var statAnalytics = document.getElementById('statAnalytics');
    var statConsent = document.getElementById('statConsent');

    // Trend badges: only shown when the API returns a trend.
    var trendJourney = document.getElementById('trendJourney');
    var trendCritical = document.getElementById('trendCriticalIssues');
    var trendAnalytics = document.getElementById('trendAnalytics');
    var trendConsent = document.getElementById('trendConsent');

    var healthRingCircle = document.getElementById('healthRingCircle');
    var healthRing = document.getElementById('healthRing');
    var healthScoreValue = document.getElementById('healthScoreValue');
    var healthOverviewMain = document.getElementById('healthOverviewMain');
    var healthOverviewError = document.getElementById('healthOverviewError');
    var healthOverviewRetry = document.getElementById('healthOverviewRetry');
    var recentList = document.getElementById('recentAuditsList');

    if (healthOverviewRetry) healthOverviewRetry.addEventListener('click', function () { loadStats(); });

    // Greeting by time of day and the signed-in user's first name.
    var greetingEl = document.getElementById('greetingName');
    if (greetingEl) {
      var hour = new Date().getHours();
      var timeGreeting = hour < 12 ? 'Good morning' : (hour < 18 ? 'Good afternoon' : 'Good evening');
      var user = window.Api.auth.getUser();
      var firstName = user && user.name ? user.name.split(' ')[0] : null;
      greetingEl.textContent = firstName ? (timeGreeting + ', ' + firstName) : timeGreeting;
    }

    // Stats and recent audits load separately, so one failing doesn't hide the other.
    loadStats();
    loadRecentAudits();

    function loadStats() {
      if (healthOverviewError) healthOverviewError.style.display = 'none';
      if (healthOverviewMain) healthOverviewMain.style.display = '';
      [statJourney, statCritical, statAnalytics, statConsent].forEach(function (el) { window.Loader.setSkeleton(el, true); });
      window.Loader.setSkeleton(healthScoreValue, true);

      return window.Api.audits.getStats()
        .then(applyStats)
        .catch(handleStatsError);
    }

    function applyStats(stats) {
        stats = stats || {};
        stats.breakdown = stats.breakdown || {};
        window.Loader.setSkeleton(statJourney, false);
        window.Loader.setSkeleton(statCritical, false);
        window.Loader.setSkeleton(statAnalytics, false);
        window.Loader.setSkeleton(statConsent, false);
        window.Loader.setSkeleton(healthScoreValue, false);

        U.animateCountUp(statCritical, stats.criticalIssues || 0, 700);
        
        // A real 0 still shows; only a module that didn't run shows "Pending".
        var hasAnalyticsScore = stats.breakdown && stats.breakdown.analytics !== null && stats.breakdown.analytics !== undefined;
        var hasConsentScore = stats.breakdown && stats.breakdown.consent !== null && stats.breakdown.consent !== undefined;
        if (statAnalytics) statAnalytics.textContent = hasAnalyticsScore ? stats.breakdown.analytics + '/100' : 'Pending';
        if (statConsent) statConsent.textContent = hasConsentScore ? stats.breakdown.consent + '/100' : 'Pending';
        var hasJourneyScore = stats.breakdown && stats.breakdown.journey !== null && stats.breakdown.journey !== undefined;
        statJourney.textContent = hasJourneyScore ? stats.breakdown.journey + '/100' : 'Pending';

        // Trend badges only when the API sends a value; never made up.
        setTrend(trendJourney, stats.trend && stats.trend.journey);
        setTrend(trendCritical, stats.trend && stats.trend.criticalIssues);
        setTrend(trendAnalytics, stats.trend && stats.trend.analytics);
        setTrend(trendConsent, stats.trend && stats.trend.consent);

        U.animateCountUp(healthScoreValue, stats.overall || 0, 900);
        U.setRingProgress(healthRingCircle, stats.overall || 0);
        U.setRingBand(healthRing, stats.overall || 0);

        // Badge follows the real overall score.
        var healthBadge = document.getElementById('healthOverviewBadge');
        var healthBadgeLabel = document.getElementById('healthOverviewBadgeLabel');
        if (healthBadge && healthBadgeLabel) {
          var band = U.scoreBand(stats.overall || 0);
          healthBadge.classList.remove('badge--success', 'badge--warning', 'badge--error');
          healthBadge.classList.add(band === 'good' ? 'badge--success' : (band === 'mid' ? 'badge--warning' : 'badge--error'));
          healthBadgeLabel.textContent = band === 'good' ? 'Healthy' : (band === 'mid' ? 'Needs attention' : 'Issues found');
          healthBadge.style.visibility = '';
        }

        setBar('barAnalytics', 'valAnalytics', stats.breakdown.analytics || 0);
        setBar('barConsent', 'valConsent', stats.breakdown.consent || 0);
        setBar('barJourney', 'valJourney', stats.breakdown.journey || 0);
    }

    // On error: show "–" (never stale numbers) and a toast with Retry.
    function handleStatsError() {
      [statJourney, statCritical, statAnalytics, statConsent].forEach(function (el) {
        window.Loader.setSkeleton(el, false);
        if (el) el.textContent = '–';
      });
      [trendJourney, trendCritical, trendAnalytics, trendConsent].forEach(function (el) { setTrend(el, null); });
      window.Loader.setSkeleton(healthScoreValue, false);
      if (healthScoreValue) healthScoreValue.textContent = '–';

      // Replace the ring with an error + Try again; the stat cards and recent audits stay.
      if (healthOverviewMain) healthOverviewMain.style.display = 'none';
      if (healthOverviewError) healthOverviewError.style.display = '';
      window.Notifications.error('Unable to load dashboard data.', 'Try again from the Health Overview card.');
    }

    // Recent audits: own loading / empty / error / data states.
    function loadRecentAudits() {
      renderRecentAuditsLoading();
      return window.Api.audits.getRecent()
        .then(function (recent) {
          renderRecentAudits(recent);
          renderRuntimeHealth(recent);
        })
        .catch(function () {
          renderRecentAuditsError();
        });
    }

    function renderRecentAuditsLoading() {
      if (!recentList) return;
      recentList.innerHTML =
        '<div class="recent-audits-loading">' +
          '<span class="recent-audits-loading__spinner" aria-hidden="true"></span>' +
          '<span>Loading dashboard...</span>' +
        '</div>';
    }

    function renderRecentAuditsError() {
      if (!recentList) return;
      recentList.innerHTML =
        '<div class="recent-audits-empty recent-audits-empty--error">' +
          '<span class="recent-audits-empty__icon recent-audits-empty__icon--error">' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v5M12 16h.01"/></svg>' +
          '</span>' +
          '<div class="recent-audits-empty__title">Unable to load dashboard data.</div>' +
          '<button type="button" class="btn btn--secondary btn--sm" id="recentAuditsRetry">Try again</button>' +
        '</div>';
      var retryBtn = document.getElementById('recentAuditsRetry');
      if (retryBtn) retryBtn.addEventListener('click', function () { loadRecentAudits(); });
    }

    function setBar(fillId, valId, value) {
      var fill = document.getElementById(fillId);
      var val = document.getElementById(valId);
      if (fill) fill.style.width = value + '%';
      if (val) { U.animateCountUp(val, value, 700); val.title = value + ' out of 100'; }
    }

    // Shows a trend badge only for a real number from the API.
    function setTrend(el, value) {
      if (!el) return;
      if (value === undefined || value === null || value === '' || isNaN(Number(value))) {
        el.hidden = true;
        el.textContent = '';
        el.classList.remove('stat-card__trend--up', 'stat-card__trend--down');
        return;
      }
      var num = Number(value);
      el.hidden = false;
      el.classList.toggle('stat-card__trend--up', num > 0);
      el.classList.toggle('stat-card__trend--down', num < 0);
      el.textContent = (num > 0 ? '▲ +' : num < 0 ? '▼ ' : '') + Math.abs(num) + '%';
    }

    // Recent audits list, straight from the API.
    var STATUS_BADGE = {
      completed: { cls: 'badge--success', label: 'Completed' },
      running: { cls: 'badge--warning', label: 'Running' },
      queued: { cls: 'badge--neutral', label: 'Queued' },
      failed: { cls: 'badge--error', label: 'Failed' }
    };

    function statusBadgeHtml(status) {
      var info = STATUS_BADGE[status] || { cls: 'badge--neutral', label: status ? U.escapeHtml(status) : 'Unknown' };
      return '<span class="badge ' + info.cls + '">' + info.label + '</span>';
    }

    function renderRecentAudits(list) {
      if (!recentList) return;
      if (!list || !list.length) {
        recentList.innerHTML =
          '<div class="recent-audits-empty">' +
            '<span class="recent-audits-empty__icon">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>' +
            '</span>' +
            '<div class="recent-audits-empty__title">No audit data available yet.</div>' +
            '<div class="recent-audits-empty__sub">Start your first website audit to see results here.</div>' +
            '<a href="audit.html" class="btn btn--primary btn--sm">New Audit</a>' +
          '</div>';
        return;
      }
      recentList.innerHTML = list.slice(0, 4).map(function (audit) {
        var isCompleted = audit.status === 'completed';
        // overallScore is only meaningful once the audit finished.
        var hasScore = isCompleted && audit.overallScore !== null && audit.overallScore !== undefined && !isNaN(Number(audit.overallScore));

        var scoreChip;
        if (hasScore) {
          var band = U.scoreBand(audit.overallScore);
          var chipClass = band === 'good' ? 'score-chip--good' : (band === 'mid' ? 'score-chip--mid' : 'score-chip--bad');
          scoreChip = '<span class="score-chip ' + chipClass + '">' + audit.overallScore + '</span>';
        } else {
          scoreChip = '<span class="score-chip score-chip--neutral">–</span>';
        }

        var dateStr = U.formatRelativeTime(audit.completedAt || audit.createdAt);

        // Only show the label line if the audit has one.
        return '' +
          '<div class="row-item">' +
            '<a class="row-item__link" href="report.html?id=' + encodeURIComponent(audit.id) + '">' +
              '<div class="row-item__favicon">' + U.escapeHtml(U.faviconLetter(audit.url)) + '</div>' +
              '<div class="row-item__body">' +
                '<div class="row-item__title">' + U.escapeHtml(audit.url) + '</div>' +
                (audit.label ? '<div class="row-item__meta">' + U.escapeHtml(audit.label) + '</div>' : '') +
              '</div>' +
              '<div class="row-item__right">' +
                '<div class="row-item__right-top">' + scoreChip + statusBadgeHtml(audit.status) + '</div>' +
                (dateStr ? '<span class="row-item__date">' + U.escapeHtml(dateStr) + '</span>' : '') +
              '</div>' +
            '</a>' +
            ((audit.status === 'running' || audit.status === 'queued') ? '' :
              '<button type="button" class="row-item__delete" data-delete-audit="' + U.escapeHtml(String(audit.id)) + '"' +
                ' data-host="' + U.escapeHtml(U.hostnameOf(audit.url)) + '"' +
                ' title="Delete this audit (you can restore it from Audit history)" aria-label="Delete audit of ' + U.escapeHtml(U.hostnameOf(audit.url)) + '">' +
                '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/></svg>' +
              '</button>') +
          '</div>';
      }).join('');

      if (!recentList.dataset.deleteWired) {
        recentList.dataset.deleteWired = '1';
        recentList.addEventListener('click', function (e) {
          var btn = e.target.closest('[data-delete-audit]');
          if (!btn || !window.Components || !window.Components.deleteAudit) return;
          e.preventDefault();
          btn.disabled = true;
          window.Components.deleteAudit(btn.getAttribute('data-delete-audit'), btn.getAttribute('data-host'), function () {
            loadRecentAudits();
            loadStats();
          }).catch(function () { btn.disabled = false; });
        });
      }

      // Point "Download PDF" at the latest audit's report.
      var pdfQuickAction = document.getElementById('downloadPdfQuickAction');
      if (pdfQuickAction && list[0]) {
        pdfQuickAction.href = 'report.html?id=' + encodeURIComponent(list[0].id);
      }
    }

    /* Analytics / Consent health */

    function renderRuntimeHealth(list) {
      var grid = document.getElementById('runtimeHealthGrid');
      if (!grid || !list || !list.length) return;

      // Only completed audits have results to show.
      var latest = list.filter(function (a) { return a.status === 'completed'; })[0];
      if (!latest) return; // nothing completed yet — no health data exists to show

      var link = 'report.html?id=' + encodeURIComponent(latest.id);

      Promise.all([
        window.Api.audits.getConsent(latest.id).catch(function () { return null; }),
        window.Api.audits.getAnalytics(latest.id).catch(function () { return null; }),
        window.Api.reports.get(latest.id).catch(function () { return null; }),
        window.Api.audits.getJourney(latest.id).catch(function () { return null; })
      ]).then(function (results) {
        var analyticsFindings = ((results[2] && results[2].findings) || []).filter(function (f) {
          return f.module === 'analytics';
        });
        var shownAny = false;
        shownAny = renderAnalyticsHealthCard(results[1], link, analyticsFindings) || shownAny;
        shownAny = renderConsentHealthCard(results[0], link) || shownAny;
        if (window.JourneyRender) shownAny = window.JourneyRender.renderDashboardCard(results[3], link) || shownAny;
        if (shownAny) grid.style.display = '';
      });
    }

    function badgeFor(passed, tested) {
      if (!tested) return { cls: 'badge--warning', label: 'Not tested' };
      return passed ? { cls: 'badge--success', label: 'Healthy' } : { cls: 'badge--error', label: 'Issues found' };
    }

    // One KPI tile. status: 'good' | 'bad' | 'warning' | 'neutral' | 'untested'.
    function kpiTile(iconSvg, label, value, sub, status) {
      return '<div class="health-kpi-tile" data-status="' + status + '">' +
        '<span class="health-kpi-tile__icon">' + iconSvg + '</span>' +
        '<div class="health-kpi-tile__content">' +
          '<span class="health-kpi-tile__label">' + U.escapeHtml(label) + '</span>' +
          '<span class="health-kpi-tile__value">' + U.escapeHtml(String(value)) + '</span>' +
          (sub ? '<span class="health-kpi-tile__sub">' + U.escapeHtml(sub) + '</span>' : '') +
        '</div>' +
      '</div>';
    }

    var ICON_TRACKERS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>';
    var ICON_TAG_MANAGER = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41 11 3.83A2 2 0 0 0 9.59 3.24L4 3a1 1 0 0 0-1 1l.24 5.59a2 2 0 0 0 .59 1.41l9.58 9.58a2 2 0 0 0 2.83 0l4.35-4.35a2 2 0 0 0 0-2.82Z"/><circle cx="7.5" cy="7.5" r="1.5"/></svg>';
    var ICON_PAGEVIEW = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z"/><circle cx="12" cy="12" r="3"/></svg>';
    var ICON_FINDINGS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
    var ICON_COOKIE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22C6.477 22 2 17.523 2 12S6.477 2 12 2s10 4.477 10 10-4.477 10-10 10zm3.6-9.6l-5.9-5.9M8.4 14.4l5.9-5.9"/></svg>';
    var ICON_SHIELD = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>';

    // Analytics health tiles from the analytics result and findings. Untested values show "Not tested".
    function renderAnalyticsHealthCard(analytics, link, findings) {
      var card = document.getElementById('analyticsHealthCard');
      var badgeEl = document.getElementById('analyticsHealthBadge');
      var body = document.getElementById('analyticsHealthBody');
      var linkEl = document.getElementById('analyticsHealthLink');
      if (!card || !analytics) return false;

      // List every tool found in the page code; one never seen in the browser counts as failed, not missing.
      var detectedVendorKeys = Object.keys(analytics.vendorConfigs || {});
      var runtimeVendors = (analytics.runtimeTested && analytics.runtimeResult && analytics.runtimeResult.vendors) || {};
      var vendors = detectedVendorKeys.map(function (k) {
        return runtimeVendors[k] || { vendor_key: k, vendor_name: k, page_view_status: 'failed' };
      });
      var trackers = analytics.trackersDetected || [];
      var trackerCount = trackers.length;
      var anyDetected = trackerCount > 0;
      var pageViewTested = analytics.runtimeTested && vendors.length > 0;
      var pageViewPassing = pageViewTested && vendors.filter(function (v) { return v.page_view_status === 'passed'; }).length;
      var allPassed = pageViewTested && pageViewPassing === vendors.length;
      // "Not tested" when no page views were tested (not "Issues found").
      var badge = badgeFor(allPassed, pageViewTested);
      var findingsCount = (findings || []).length;

      badgeEl.className = 'badge ' + badge.cls;
      badgeEl.textContent = badge.label;

      var tiles = [];

      tiles.push(kpiTile(
        ICON_TRACKERS,
        'Trackers detected',
        trackerCount,
        trackerCount ? trackers.slice(0, 3).join(', ') + (trackerCount > 3 ? ', …' : '') : 'None found',
        anyDetected ? 'neutral' : 'warning'
      ));

      tiles.push(kpiTile(
        ICON_TAG_MANAGER,
        'Tag Manager',
        analytics.tagManagerDetected ? 'Detected' : 'Not detected',
        analytics.gtmContainerId || '',
        analytics.tagManagerDetected ? 'good' : 'warning'
      ));

      if (pageViewTested) {
        tiles.push(kpiTile(
          ICON_PAGEVIEW,
          'Page View Tracking',
          pageViewPassing + ' / ' + vendors.length + ' passing',
          '',
          allPassed ? 'good' : 'bad'
        ));
      } else {
        tiles.push(kpiTile(ICON_PAGEVIEW, 'Page View Tracking', 'Not tested', '', 'untested'));
      }

      tiles.push(kpiTile(
        ICON_FINDINGS,
        'Findings',
        findingsCount,
        findingsCount ? '' : 'No issues',
        findingsCount ? 'bad' : 'good'
      ));

      // Page-view chip per tool, only when the live check ran. Tools missing from it show as failing.
      if (pageViewTested) {
        var chips = vendors.map(function (v) {
          var passed = v.page_view_status === 'passed';
          return '<span class="health-vendor-chip" data-status="' + (passed ? 'good' : 'bad') + '">' +
            '<span class="health-vendor-chip__dot"></span>' +
            U.escapeHtml(v.vendor_name || v.vendor_key) + ' — ' + (passed ? 'Passing' : 'Failing') +
          '</span>';
        }).join('');
        tiles.push('<div class="health-vendor-chips">' + chips + '</div>');
      }

      // Cross-page differences (full-site audits only).
      var crossPageFindings = analytics.crossPageFindings || [];
      var crossPageHtml = '';
      if (crossPageFindings.length) {
        crossPageHtml = '<div class="health-runtime-note">' +
          U.escapeHtml(crossPageFindings.length + ' cross-page consistency issue' + (crossPageFindings.length === 1 ? '' : 's') + ' found across the site') +
        '</div>';
      }

      body.innerHTML = tiles.join('') + crossPageHtml;
      linkEl.href = link + '#analytics';

      card.style.display = '';
      return true;
    }

    // Same icons as report.js.
  var PASS_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4L19 7"/></svg>';
  var FAIL_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>';

  // API value -> { ok, tested }: true = pass, false = fail, null = not tested.
  function checkResultFromValue(value) {
    return { ok: value === true, tested: value === true || value === false };
  }

  // One ✓/✕/○ row per check.
  function renderCheckListRows(checkItems, checksMap) {
    return checkItems.map(function (item) {
      var result = checkResultFromValue(checksMap[item.key]);
      var cls = !result.tested ? 'check-item--pending' : (result.ok ? 'check-item--pass' : 'check-item--fail');
      var icon = !result.tested ? '' : (result.ok ? PASS_ICON : FAIL_ICON);
      return '<div class="check-item ' + cls + '"><span class="check-item__icon">' + icon + '</span><span class="check-item__label">' +
        U.escapeHtml(item.label) + (result.tested ? '' : ' (not tested)') + '</span></div>';
    }).join('');
  }

  // One GDPR or CCPA row ("Failed/Passed · N issues"), with a "Why did it fail?"
  // list of the failed checks when it failed. Uses the backend's check results.
    function renderComplianceRow(label, compliant, checkItems, checksMap) {
      var failed = checkItems.filter(function (c) { return checksMap[c.key] === false; });
      var badge = compliant
        ? { cls: 'badge--success', label: 'Passed' }
        : { cls: 'badge--error', label: 'Failed' };
      var countLabel = compliant ? '' :
        (' · ' + failed.length + ' issue' + (failed.length === 1 ? '' : 's'));

      var html = '<div class="health-compliance-row">' +
        '<span class="health-compliance-row__label">' + U.escapeHtml(label) + '</span>' +
        '<span class="badge ' + badge.cls + '">' +
          U.escapeHtml(badge.label) + U.escapeHtml(countLabel) + '</span>' +
        '</div>';

      if (!compliant && failed.length) {
        html += '<details class="health-compliance-detail">' +
          '<summary>' + U.escapeHtml(label) + ' — Why did it fail?</summary>' +
          '<ul>' +
          failed.map(function (c) {
            var dot = c.severity === 'critical' ? '\ud83d\udd34' : '\ud83d\udfe0';
            return '<li>' + dot + ' ' + U.escapeHtml(c.failReason || c.label) + '</li>';
          }).join('') +
          '</ul></details>';
      }
      return html;
    }

    // Consent health tiles (banner, GDPR, CCPA) and the "why did it fail" lists.
    function renderConsentHealthCard(consent, link) {
      var card = document.getElementById('consentHealthCard');
      var badgeEl = document.getElementById('consentHealthBadge');
      var body = document.getElementById('consentHealthBody');
      var linkEl = document.getElementById('consentHealthLink');
      if (!card || !consent) return false;

      // Only laws that apply to the region are judged; older audits show GDPR + CCPA.
      var app = consent.applicability || {};
      var hasApp = !!(app.frameworks && app.frameworks.length);
      var applicable = hasApp ? (app.applicable_frameworks || []) : ['gdpr', 'ccpa'];
      var applies = function (fw) { return applicable.indexOf(fw) !== -1; };
      var dpdpFw = (app.frameworks || []).filter(function (f) { return f.key === 'dpdp' && f.applicable; })[0];
      var dpdpOk = !!(dpdpFw && dpdpFw.assessment && dpdpFw.assessment.status === 'pass');

      var coreOk = !!consent.hasCookieBanner &&
        (!applies('gdpr') || !!consent.gdprCompliant) &&
        (!applies('ccpa') || !!consent.ccpaCompliant) &&
        (!applies('dpdp') || dpdpOk);
      var badge = badgeFor(coreOk, true);
      badgeEl.className = 'badge ' + badge.cls;
      badgeEl.textContent = badge.label;

      var tiles = [
        kpiTile(
          ICON_COOKIE,
          'Cookie Banner',
          consent.hasCookieBanner ? 'Detected' : 'Not detected',
          '',
          consent.hasCookieBanner ? 'good' : 'bad'
        ),
        kpiTile(
          ICON_SHIELD,
          'GDPR',
          !applies('gdpr') ? 'Not assessed' : (consent.gdprCompliant ? 'Passed' : 'Failed'),
          '',
          !applies('gdpr') ? 'neutral' : (consent.gdprCompliant ? 'good' : 'bad')
        ),
        kpiTile(
          ICON_SHIELD,
          'CCPA',
          !applies('ccpa') ? 'Not assessed' : (consent.ccpaCompliant ? 'Passed' : 'Failed'),
          '',
          !applies('ccpa') ? 'neutral' : (consent.ccpaCompliant ? 'good' : 'bad')
        )
      ];
      if (hasApp) {
        tiles.unshift(kpiTile(
          ICON_SHIELD,
          'Region',
          app.region_label || 'Unknown',
          (app.confidence ? app.confidence + ' confidence' : ''),
          app.regional_compliance === 'assessed' ? 'neutral' : 'warning'
        ));
      }
      if (applies('dpdp')) {
        tiles.push(kpiTile(ICON_SHIELD, 'DPDP', dpdpOk ? 'Passed' : 'Failed', '', dpdpOk ? 'good' : 'bad'));
      }

      var complianceHtml = '<div class="health-compliance-block">' +
        (applies('gdpr')
          ? '<div class="health-compliance-checklist">' + renderCheckListRows(GDPR_CHECK_ITEMS, consent.gdprChecks || {}) + '</div>' +
            renderComplianceRow('GDPR', consent.gdprCompliant, GDPR_CHECK_ITEMS, consent.gdprChecks || {})
          : '') +
        (applies('ccpa')
          ? '<div class="health-compliance-checklist">' + renderCheckListRows(CCPA_CHECK_ITEMS, consent.ccpaChecks || {}) + '</div>' +
            renderComplianceRow('CCPA', consent.ccpaCompliant, CCPA_CHECK_ITEMS, consent.ccpaChecks || {})
          : '') +
        (hasApp && app.regional_compliance !== 'assessed'
          ? '<div class="health-runtime-note">Regional compliance: Not assessed — the site\'s region could not be established, so only the technical consent scan was run.</div>'
          : '') +
      '</div>';

      // Live Accept/Reject results, as an extra note.
      var runtimeHtml = '';
      if (consent.runtimeTested) {
        var rr = consent.runtimeResult || {};
        // runtime_result keys arrive in camelCase.
        var rejectV = rr.rejectBlocksTracking !== undefined ? rr.rejectBlocksTracking : rr.reject_blocks_tracking;
        var acceptV = rr.acceptAllowsTracking !== undefined ? rr.acceptAllowsTracking : rr.accept_allows_tracking;
        var rejectKnown = rejectV !== null && rejectV !== undefined;
        var acceptKnown = acceptV !== null && acceptV !== undefined;
        runtimeHtml = '<div class="health-runtime-note">Runtime-verified: Reject ' +
          (rejectKnown ? (rejectV ? 'blocks tracking' : 'does not block tracking') : 'not verified') +
          ' · Accept ' +
          (acceptKnown ? (acceptV ? 'allows tracking' : 'does not allow tracking') : 'not verified') +
          '</div>';
      }

      body.innerHTML = tiles.join('') + complianceHtml + runtimeHtml;
      linkEl.href = link + '#consent';

      card.style.display = '';
      return true;
    }
  });
})();
