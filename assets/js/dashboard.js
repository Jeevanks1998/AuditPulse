/* ==========================================================================
   dashboard.js — dashboard.html page logic
   ========================================================================== */

(function () {
  var U = window.Utils;

  // Mirrors backend consent.consent_score.GDPR_CHECK_ORDER / GDPR_CHECK_LABELS —
  // keep the key list, order, and severity/failReason text in sync with that
  // module (same source data assets/js/report.js's GDPR_CHECK_ITEMS uses, so
  // the "why did it fail" wording matches between dashboard and report).
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

  // Mirrors backend consent.consent_score.CCPA_CHECK_ORDER / CCPA_CHECK_LABELS —
  // same relationship CCPA_CHECK_ITEMS in report.js has to that module.
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
    var statPerf = document.getElementById('statPerformance');
    if (!statPerf || !window.Api) return; // not on dashboard.html

    var statCritical = document.getElementById('statCriticalIssues');
    var statAnalytics = document.getElementById('statAnalytics');
    var statConsent = document.getElementById('statConsent');

    // Trend indicators are optional — only shown when the API actually
    // returns a trend value for that KPI. Nothing here is invented.
    var trendPerf = document.getElementById('trendPerformance');
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

    // Real time-of-day + real logged-in user's first name — replaces the
    // old hardcoded "Good morning, Jeevan" that showed regardless of the
    // time or who was actually signed in.
    var greetingEl = document.getElementById('greetingName');
    if (greetingEl) {
      var hour = new Date().getHours();
      var timeGreeting = hour < 12 ? 'Good morning' : (hour < 18 ? 'Good afternoon' : 'Good evening');
      var user = window.Api.auth.getUser();
      var firstName = user && user.name ? user.name.split(' ')[0] : null;
      greetingEl.textContent = firstName ? (timeGreeting + ', ' + firstName) : timeGreeting;
    }

    // Stats/health and Recent Audits are fetched and rendered independently
    // (not Promise.all'd together) so that a failure in one never wipes out
    // data that successfully loaded in the other — e.g. if /audits/recent
    // errors out but /audits/stats succeeds, the KPI cards and health ring
    // still render normally, and vice versa. Each section owns its own
    // loading → data / empty / error states.
    loadStats();
    loadRecentAudits();

    function loadStats() {
      if (healthOverviewError) healthOverviewError.style.display = 'none';
      if (healthOverviewMain) healthOverviewMain.style.display = '';
      [statPerf, statCritical, statAnalytics, statConsent].forEach(function (el) { window.Loader.setSkeleton(el, true); });
      window.Loader.setSkeleton(healthScoreValue, true);

      return window.Api.audits.getStats()
        .then(applyStats)
        .catch(handleStatsError);
    }

    function applyStats(stats) {
        stats = stats || {};
        stats.breakdown = stats.breakdown || {};
        window.Loader.setSkeleton(statPerf, false);
        window.Loader.setSkeleton(statCritical, false);
        window.Loader.setSkeleton(statAnalytics, false);
        window.Loader.setSkeleton(statConsent, false);
        window.Loader.setSkeleton(healthScoreValue, false);

        U.animateCountUp(statPerf, stats.performanceScore || 0, 700, '%');
        U.animateCountUp(statCritical, stats.criticalIssues || 0, 700);
        
        // Display Analytics and Consent status — a real 0% score must still
        // render as "0%", not "Pending". Only an actually-missing value
        // (module wasn't run, so breakdown.analytics/consent is null/
        // undefined) falls back to "Pending".
        var hasAnalyticsScore = stats.breakdown && stats.breakdown.analytics !== null && stats.breakdown.analytics !== undefined;
        var hasConsentScore = stats.breakdown && stats.breakdown.consent !== null && stats.breakdown.consent !== undefined;
        if (statAnalytics) statAnalytics.textContent = hasAnalyticsScore ? stats.breakdown.analytics + '%' : 'Pending';
        if (statConsent) statConsent.textContent = hasConsentScore ? stats.breakdown.consent + '%' : 'Pending';

        // Trend badges: rendered only when the API supplies a value for
        // that KPI (stats.trend.<key>). No trend is ever fabricated — if
        // the backend hasn't added trend data yet, these stay hidden,
        // exactly as they are today.
        setTrend(trendPerf, stats.trend && stats.trend.performance);
        setTrend(trendCritical, stats.trend && stats.trend.criticalIssues);
        setTrend(trendAnalytics, stats.trend && stats.trend.analytics);
        setTrend(trendConsent, stats.trend && stats.trend.consent);

        U.animateCountUp(healthScoreValue, stats.overall || 0, 900);
        U.setRingProgress(healthRingCircle, stats.overall || 0);
        U.setRingBand(healthRing, stats.overall || 0);

        // Health-overview badge reflects the real overall score (band computed
        // the same way as the ring itself) rather than the static "Healthy"
        // markup this element started as.
        var healthBadge = document.getElementById('healthOverviewBadge');
        var healthBadgeLabel = document.getElementById('healthOverviewBadgeLabel');
        if (healthBadge && healthBadgeLabel) {
          var band = U.scoreBand(stats.overall || 0);
          healthBadge.classList.remove('badge--success', 'badge--warning', 'badge--error');
          healthBadge.classList.add(band === 'good' ? 'badge--success' : (band === 'mid' ? 'badge--warning' : 'badge--error'));
          healthBadgeLabel.textContent = band === 'good' ? 'Healthy' : (band === 'mid' ? 'Needs attention' : 'Issues found');
          healthBadge.style.visibility = '';
        }

        setBar('barPerformance', 'valPerformance', stats.breakdown.performance || 0);
        setBar('barAccessibility', 'valAccessibility', stats.breakdown.accessibility || 0);
        setBar('barSecurity', 'valSecurity', stats.breakdown.security || 0);
        setBar('barAnalytics', 'valAnalytics', stats.breakdown.analytics || 0);
        setBar('barConsent', 'valConsent', stats.breakdown.consent || 0);
    }

    // KPI cards, trend badges, and the health ring all fall back to "–" /
    // hidden rather than a stale or fabricated number, and a single toast
    // (with a real retry, not just "refresh the page") lets the person
    // recover without reloading the whole dashboard.
    function handleStatsError() {
      [statPerf, statCritical, statAnalytics, statConsent].forEach(function (el) {
        window.Loader.setSkeleton(el, false);
        if (el) el.textContent = '–';
      });
      [trendPerf, trendCritical, trendAnalytics, trendConsent].forEach(function (el) { setTrend(el, null); });
      window.Loader.setSkeleton(healthScoreValue, false);
      if (healthScoreValue) healthScoreValue.textContent = '–';

      // Swap the ring/category grid for an inline "Unable to load dashboard
      // data. / Try again" state with a real retry button — the KPI stat
      // cards above stay visible showing "–" rather than the whole card
      // disappearing, and Recent Audits is unaffected either way.
      if (healthOverviewMain) healthOverviewMain.style.display = 'none';
      if (healthOverviewError) healthOverviewError.style.display = '';
      window.Notifications.error('Unable to load dashboard data.', 'Try again from the Health Overview card.');
    }

    // Recent Audits owns its own loading / empty / error / data states,
    // independent of the stats fetch above — see the comment where
    // loadStats()/loadRecentAudits() are kicked off.
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
      if (val) U.animateCountUp(val, value, 700);
    }

    // Shows a KPI card's trend badge only when `value` is an actual number
    // from the API (e.g. stats.trend.performance). Any missing/undefined/
    // null value keeps the badge hidden rather than showing a placeholder
    // or a made-up figure.
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

    // Renders GET /audits/recent straight into the Recent Audits list —
    // url, overall_score, status, and completed_at/created_at all come
    // from the API response (mapAudit in api.js). No placeholder rows.
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
        var hasScore = isCompleted && audit.score !== null && audit.score !== undefined && !isNaN(Number(audit.score));

        var scoreChip;
        if (hasScore) {
          var band = U.scoreBand(audit.score);
          var chipClass = band === 'good' ? 'score-chip--good' : (band === 'mid' ? 'score-chip--mid' : 'score-chip--bad');
          scoreChip = '<span class="score-chip ' + chipClass + '">' + audit.score + '</span>';
        } else {
          scoreChip = '<span class="score-chip score-chip--neutral">–</span>';
        }

        var dateStr = U.formatRelativeTime(audit.completedAt || audit.createdAt);

        // Partial data: the label/meta line only renders when the API
        // actually returned one — no empty placeholder row for audits
        // that don't have a label.
        return '' +
          '<a class="row-item" href="report.html?id=' + encodeURIComponent(audit.id) + '" style="text-decoration:none; color:inherit;">' +
            '<div class="row-item__favicon">' + U.escapeHtml(U.faviconLetter(audit.url)) + '</div>' +
            '<div class="row-item__body">' +
              '<div class="row-item__title">' + U.escapeHtml(audit.url) + '</div>' +
              (audit.label ? '<div class="row-item__meta">' + U.escapeHtml(audit.label) + '</div>' : '') +
            '</div>' +
            '<div class="row-item__right">' +
              '<div class="row-item__right-top">' + scoreChip + statusBadgeHtml(audit.status) + '</div>' +
              (dateStr ? '<span class="row-item__date">' + U.escapeHtml(dateStr) + '</span>' : '') +
            '</div>' +
          '</a>';
      }).join('');

      // Point the "Download PDF" quick-action card at the most recent
      // audit's report so it's a real link rather than the static
      // report.html placeholder.
      var pdfQuickAction = document.getElementById('downloadPdfQuickAction');
      if (pdfQuickAction && list[0]) {
        pdfQuickAction.href = 'report.html?id=' + encodeURIComponent(list[0].id);
      }
    }

    /* --------------------------- Analytics / Consent Health (§6) --------------------------- */

    function renderRuntimeHealth(list) {
      var grid = document.getElementById('runtimeHealthGrid');
      if (!grid || !list || !list.length) return;

      var latest = list[0];
      var link = 'report.html?id=' + encodeURIComponent(latest.id);

      Promise.all([
        window.Api.audits.getConsent(latest.id).catch(function () { return null; }),
        window.Api.audits.getAnalytics(latest.id).catch(function () { return null; }),
        window.Api.reports.get(latest.id).catch(function () { return null; })
      ]).then(function (results) {
        var analyticsFindings = ((results[2] && results[2].findings) || []).filter(function (f) {
          return f.module === 'analytics';
        });
        var shownAny = false;
        shownAny = renderAnalyticsHealthCard(results[1], link, analyticsFindings) || shownAny;
        shownAny = renderConsentHealthCard(results[0], link) || shownAny;
        if (shownAny) grid.style.display = '';
      });
    }

    function badgeFor(passed, tested) {
      if (!tested) return { cls: 'badge--warning', label: 'Not tested' };
      return passed ? { cls: 'badge--success', label: 'Healthy' } : { cls: 'badge--error', label: 'Issues found' };
    }

    // Builds one KPI tile. `status` drives the color treatment and must be
    // one of 'good' | 'bad' | 'warning' | 'neutral' | 'untested' — callers
    // pass 'untested' whenever the underlying field genuinely wasn't
    // evaluated for this audit, rather than coercing a missing value into
    // a fake pass or fail.
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

    // Renders the Analytics Health KPI grid straight from the
    // /audits/{id}/analytics response (mapAnalytics in api.js) plus the
    // matching report's analytics-module findings. Every value below reads
    // an actual API field — nothing here is invented to fill space; a
    // field that wasn't evaluated (e.g. runtime page-view validation on an
    // audit that didn't run it) renders "Not tested" instead of a 0/false.
    function renderAnalyticsHealthCard(analytics, link, findings) {
      var card = document.getElementById('analyticsHealthCard');
      var badgeEl = document.getElementById('analyticsHealthBadge');
      var body = document.getElementById('analyticsHealthBody');
      var linkEl = document.getElementById('analyticsHealthLink');
      if (!card || !analytics) return false;

      // Vendor list is built from every vendor actually detected in the
      // page's markup (vendorConfigs) — not just the ones that show up in
      // runtimeResult.vendors. The runtime pass only ever records a vendor
      // that captured at least one request, so a vendor that was detected
      // but never fired a single tracking request at runtime is *absent*
      // from runtimeResult.vendors, not present-and-passing. Treating that
      // absence as "failed" (same convention report.js uses for its
      // Detection & Runtime table) keeps a totally broken vendor visible
      // instead of silently vanishing from the count and chip list.
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
      // Badge reflects whether page-view testing actually ran (pageViewTested),
      // not just the coarser runtimeTested flag — a runtime pass that found
      // zero vendors to test is "Not tested", not "Issues found".
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

      // Per-vendor page-view breakdown — only rendered when the runtime
      // pass actually ran. Covers every statically-detected vendor
      // (vendorConfigs), cross-referenced against analytics.runtimeResult.vendors —
      // a detected vendor missing from the runtime result renders as
      // "Failing", not as an omitted vendor.
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

      // Cross-page consistency (multi-page audits only) — real discrepancies
      // computed by the backend across every crawled page, straight from
      // analytics.crossPageFindings. Left out entirely on a homepage-only
      // audit, where the backend always returns [] for this field.
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

    // Renders one compliance roll-up (GDPR or CCPA) as a "<Label> — Failed/Passed
    // · N issues" row, plus — only when it failed — a collapsible "Why did it
    // fail?" disclosure listing the specific checks that failed, each marked
    // 🔴 (critical) or 🟠 (warning). Reads straight from `checksMap`
    // (consent.gdprChecks / consent.ccpaChecks) and the matching *_CHECK_ITEMS
    // array above — no separate issue list is built for this, the backend's
    // gdpr_checks/ccpa_checks dicts are the single source of truth for
    // "what's missing".
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

    // Renders the Consent Health section straight from /audits/{id}/consent
    // (mapConsent in api.js): a Cookie Banner / GDPR / CCPA KPI tile row —
    // the three fields this card is scoped to — plus the existing GDPR/CCPA
    // "why did it fail" disclosures. A field with no corresponding API value
    // (e.g. there is no consent-decision logging endpoint in this backend)
    // is intentionally left out rather than shown with a made-up value.
    function renderConsentHealthCard(consent, link) {
      var card = document.getElementById('consentHealthCard');
      var badgeEl = document.getElementById('consentHealthBadge');
      var body = document.getElementById('consentHealthBody');
      var linkEl = document.getElementById('consentHealthLink');
      if (!card || !consent) return false;

      var coreOk = !!consent.hasCookieBanner && !!consent.gdprCompliant && !!consent.ccpaCompliant;
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
          consent.gdprCompliant ? 'Passed' : 'Failed',
          '',
          consent.gdprCompliant ? 'good' : 'bad'
        ),
        kpiTile(
          ICON_SHIELD,
          'CCPA',
          consent.ccpaCompliant ? 'Passed' : 'Failed',
          '',
          consent.ccpaCompliant ? 'good' : 'bad'
        )
      ];

      var complianceHtml = '<div class="health-compliance-block">' +
        renderComplianceRow('GDPR', consent.gdprCompliant, GDPR_CHECK_ITEMS, consent.gdprChecks || {}) +
        renderComplianceRow('CCPA', consent.ccpaCompliant, CCPA_CHECK_ITEMS, consent.ccpaChecks || {}) +
      '</div>';

      // Real runtime-verified enforcement (does Reject actually block
      // tracking, does Accept actually allow it) — kept as a supplementary
      // note since it's genuine data from consent.runtimeResult, distinct
      // from the GDPR/CCPA checklist above.
      var runtimeHtml = '';
      if (consent.runtimeTested) {
        var rr = consent.runtimeResult || {};
        var rejectKnown = rr.reject_blocks_tracking !== null && rr.reject_blocks_tracking !== undefined;
        var acceptKnown = rr.accept_allows_tracking !== null && rr.accept_allows_tracking !== undefined;
        runtimeHtml = '<div class="health-runtime-note">Runtime-verified: Reject ' +
          (rejectKnown ? (rr.reject_blocks_tracking ? 'blocks tracking' : 'does not block tracking') : 'not verified') +
          ' · Accept ' +
          (acceptKnown ? (rr.accept_allows_tracking ? 'allows tracking' : 'does not allow tracking') : 'not verified') +
          '</div>';
      }

      body.innerHTML = tiles.join('') + complianceHtml + runtimeHtml;
      linkEl.href = link + '#consent';

      card.style.display = '';
      return true;
    }
  });
})();
