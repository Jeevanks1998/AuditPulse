/* ==========================================================================
   dashboard.js — dashboard.html page logic
   ========================================================================== */

(function () {
  var U = window.Utils;

  document.addEventListener('DOMContentLoaded', function () {
    var statTotal = document.getElementById('statTotalAudits');
    if (!statTotal || !window.Api) return; // not on dashboard.html

    var statSeo = document.getElementById('statSeoIssues');
    var statPerf = document.getElementById('statPerformance');
    var statCritical = document.getElementById('statCriticalIssues');
    var statAnalytics = document.getElementById('statAnalytics');
    var statConsent = document.getElementById('statConsent');

    var healthRingCircle = document.getElementById('healthRingCircle');
    var healthRing = document.getElementById('healthRing');
    var healthScoreValue = document.getElementById('healthScoreValue');
    var recentList = document.getElementById('recentAuditsList');

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

    [statTotal, statSeo, statPerf, statCritical, statAnalytics, statConsent].forEach(function (el) { window.Loader.setSkeleton(el, true); });
    window.Loader.setSkeleton(healthScoreValue, true);

    Promise.all([window.Api.audits.getStats(), window.Api.audits.getRecent()])
      .then(function (results) {
        var stats = results[0];
        var recent = results[1];

        window.Loader.setSkeleton(statTotal, false);
        window.Loader.setSkeleton(statSeo, false);
        window.Loader.setSkeleton(statPerf, false);
        window.Loader.setSkeleton(statCritical, false);
        window.Loader.setSkeleton(statAnalytics, false);
        window.Loader.setSkeleton(statConsent, false);
        window.Loader.setSkeleton(healthScoreValue, false);

        U.animateCountUp(statTotal, stats.totalAudits, 700);
        U.animateCountUp(statSeo, stats.seoIssues, 700);
        U.animateCountUp(statPerf, stats.performanceScore, 700, '%');
        U.animateCountUp(statCritical, stats.criticalIssues, 700);
        
        // Display Analytics and Consent status
        if (statAnalytics) statAnalytics.textContent = (stats.breakdown && stats.breakdown.analytics ? stats.breakdown.analytics + '%' : 'Pending');
        if (statConsent) statConsent.textContent = (stats.breakdown && stats.breakdown.consent ? stats.breakdown.consent + '%' : 'Pending');

        U.animateCountUp(healthScoreValue, stats.overall, 900);
        U.setRingProgress(healthRingCircle, stats.overall);
        U.setRingBand(healthRing, stats.overall);

        // Health-overview badge reflects the real overall score (band computed
        // the same way as the ring itself) rather than the static "Healthy"
        // markup this element started as.
        var healthBadge = document.getElementById('healthOverviewBadge');
        var healthBadgeLabel = document.getElementById('healthOverviewBadgeLabel');
        if (healthBadge && healthBadgeLabel) {
          var band = U.scoreBand(stats.overall);
          healthBadge.classList.remove('badge--success', 'badge--warning', 'badge--error');
          healthBadge.classList.add(band === 'good' ? 'badge--success' : (band === 'mid' ? 'badge--warning' : 'badge--error'));
          healthBadgeLabel.textContent = band === 'good' ? 'Healthy' : (band === 'mid' ? 'Needs attention' : 'Issues found');
          healthBadge.style.visibility = '';
        }

        setBar('barSeo', 'valSeo', stats.breakdown.seo);
        setBar('barPerformance', 'valPerformance', stats.breakdown.performance);
        setBar('barAccessibility', 'valAccessibility', stats.breakdown.accessibility);
        setBar('barSecurity', 'valSecurity', stats.breakdown.security);
        setBar('barAnalytics', 'valAnalytics', stats.breakdown.analytics || 0);
        setBar('barConsent', 'valConsent', stats.breakdown.consent || 0);

        renderRecentAudits(recent);
        renderRuntimeHealth(recent);
      })
      .catch(function () {
        window.Notifications.error('Couldn\'t load dashboard', 'Please refresh the page to try again.');
        [statTotal, statSeo, statPerf, statCritical, statAnalytics, statConsent].forEach(function (el) {
          window.Loader.setSkeleton(el, false);
          if (el) el.textContent = '–';
        });
        window.Loader.setSkeleton(healthScoreValue, false);
        if (healthScoreValue) healthScoreValue.textContent = '–';
        if (recentList) {
          recentList.innerHTML = '<div class="row-item-empty" style="padding: var(--sp-4); color: var(--text-tertiary); font-size: var(--fs-sm);">Couldn\'t load recent audits.</div>';
        }
      });

    function setBar(fillId, valId, value) {
      var fill = document.getElementById(fillId);
      var val = document.getElementById(valId);
      if (fill) fill.style.width = value + '%';
      if (val) U.animateCountUp(val, value, 700);
    }

    function renderRecentAudits(list) {
      if (!recentList) return;
      if (!list || !list.length) {
        recentList.innerHTML = '<div class="row-item-empty" style="padding: var(--sp-4); color: var(--text-tertiary); font-size: var(--fs-sm);">No audits yet — run your first audit to see it here.</div>';
        return;
      }
      recentList.innerHTML = list.slice(0, 4).map(function (audit) {
        var band = U.scoreBand(audit.score);
        var chipClass = band === 'good' ? 'score-chip--good' : (band === 'mid' ? 'score-chip--mid' : 'score-chip--bad');
        return '' +
          '<a class="row-item" href="report.html?id=' + encodeURIComponent(audit.id) + '" style="text-decoration:none; color:inherit;">' +
            '<div class="row-item__favicon">' + U.escapeHtml(U.faviconLetter(audit.url)) + '</div>' +
            '<div class="row-item__body">' +
              '<div class="row-item__title">' + U.escapeHtml(audit.url) + '</div>' +
              '<div class="row-item__meta">' + U.formatRelativeTime(audit.completedAt) + ' · ' + U.escapeHtml(audit.label) + '</div>' +
            '</div>' +
            '<span class="score-chip ' + chipClass + '">' + audit.score + '</span>' +
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

    function checkRow(label, ok, tested) {
      var isTested = tested !== false;
      var color = !isTested ? 'var(--text-tertiary)' : (ok ? 'var(--color-success, #16a34a)' : 'var(--color-error, #dc2626)');
      var mark = !isTested ? '–' : (ok ? '✓' : '✕');
      return '<div style="display:flex; align-items:center; justify-content:space-between; font-size: var(--fs-sm);">' +
        '<span>' + U.escapeHtml(label) + '</span>' +
        '<span style="color:' + color + '; font-weight:600;">' + mark + (isTested ? '' : ' not tested') + '</span>' +
      '</div>';
    }

    function renderAnalyticsHealthCard(analytics, link, findings) {
      var card = document.getElementById('analyticsHealthCard');
      var badgeEl = document.getElementById('analyticsHealthBadge');
      var body = document.getElementById('analyticsHealthBody');
      var linkEl = document.getElementById('analyticsHealthLink');
      if (!card || !analytics) return false;

      var vendors = analytics.runtimeTested && analytics.runtimeResult ? Object.values(analytics.runtimeResult.vendors || {}) : [];
      var trackerCount = (analytics.trackersDetected || []).length;
      var anyDetected = trackerCount > 0;
      var allPassed = vendors.length > 0 && vendors.every(function (v) { return v.page_view_status === 'passed'; });
      var badge = badgeFor(allPassed, analytics.runtimeTested);
      var findingsCount = (findings || []).length;

      badgeEl.className = 'badge ' + badge.cls;
      badgeEl.textContent = badge.label;

      // Tracker count and event-validation status both come straight from
      // the current audit response — never hard-coded.
      var rows = [
        '<div style="display:flex; align-items:center; justify-content:space-between; font-size: var(--fs-sm);">' +
          '<span>Trackers detected</span><span style="font-weight:600;">' + trackerCount + '</span></div>',
        checkRow('Tag Manager detected', !!analytics.tagManagerDetected, anyDetected)
      ];
      if (analytics.runtimeTested && vendors.length) {
        vendors.forEach(function (v) {
          rows.push(checkRow((v.vendor_name || v.vendor_key) + ' — Page View', v.page_view_status === 'passed', true));
        });
      } else {
        rows.push(checkRow('Runtime validation (Page View/Scroll/Click)', false, false));
      }
      rows.push('<div style="display:flex; align-items:center; justify-content:space-between; font-size: var(--fs-sm);">' +
        '<span>Analytics findings</span><span style="font-weight:600; color:' +
        (findingsCount ? 'var(--color-error, #dc2626)' : 'var(--color-success, #16a34a)') + ';">' + findingsCount + '</span></div>');

      body.innerHTML = rows.join('');
      linkEl.href = link + '#analytics';

      card.style.display = '';
      return true;
    }

    function renderConsentHealthCard(consent, link) {
      var card = document.getElementById('consentHealthCard');
      var badgeEl = document.getElementById('consentHealthBadge');
      var body = document.getElementById('consentHealthBody');
      var linkEl = document.getElementById('consentHealthLink');
      if (!card || !consent) return false;

      var coreOk = !!consent.hasCookieBanner && !!consent.gdprCompliant;
      var badge = badgeFor(coreOk, true);
      badgeEl.className = 'badge ' + badge.cls;
      badgeEl.textContent = badge.label;

      var rows = [
        checkRow('Cookie banner detected', consent.hasCookieBanner),
        checkRow('GDPR compliant', consent.gdprCompliant),
        checkRow('CCPA compliant', consent.ccpaCompliant)
      ];
      if (consent.runtimeTested) {
        var rr = consent.runtimeResult || {};
        rows.push(checkRow('Reject blocks tracking', !!rr.reject_blocks_tracking, rr.reject_blocks_tracking !== null && rr.reject_blocks_tracking !== undefined));
        rows.push(checkRow('Accept allows tracking', !!rr.accept_allows_tracking, rr.accept_allows_tracking !== null && rr.accept_allows_tracking !== undefined));
      } else {
        rows.push(checkRow('Reject / Accept runtime checks', false, false));
      }
      body.innerHTML = rows.join('');
      linkEl.href = link + '#consent';

      card.style.display = '';
      return true;
    }
  });
})();
