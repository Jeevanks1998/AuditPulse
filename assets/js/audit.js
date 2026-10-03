/* ==========================================================================
   audit.js — audit.html page logic: form state, module toggles,
   start-audit progress simulation, redirect to report.html on completion
   ========================================================================== */

(function () {
  var U = window.Utils;
  var V = window.Validation;
  var CFG = window.APP_CONFIG;

  document.addEventListener('DOMContentLoaded', function () {
    var urlInput = document.getElementById('auditUrlInput');
    if (!urlInput || !window.Api) return; // not on audit.html

    var urlError = document.getElementById('urlError');
    var urlWrap = urlInput.closest('.url-input-wrap');

    var depthHomepage = document.getElementById('depthHomepage');
    var depthFull = document.getElementById('depthFull');
    var maxPagesInput = document.getElementById('maxPagesInput');
    var stepperMinus = document.getElementById('stepperMinus');
    var stepperPlus = document.getElementById('stepperPlus');

    var moduleList = document.getElementById('moduleList');
    var moduleCountBadge = document.getElementById('moduleCountBadge');

    var summaryTarget = document.getElementById('summaryTarget');
    var summaryDepth = document.getElementById('summaryDepth');
    var summaryMaxPages = document.getElementById('summaryMaxPages');
    var summaryModules = document.getElementById('summaryModules');
    var summaryEta = document.getElementById('summaryEta');

    var startBtn = document.getElementById('startAuditBtn');
    var progressSection = document.getElementById('progressSection');
    var checkList = document.getElementById('checkList');
    var taskEta = document.getElementById('taskEta');
    var progressRingCircle = document.getElementById('progressRingCircle');
    var progressPercentLabel = document.getElementById('progressPercentLabel');
    var progressHeading = document.getElementById('progressHeading');
    var progressStatusText = document.getElementById('progressStatusText');
    var etaValue = document.getElementById('etaValue');

    var totalModules = CFG.MODULES.length;

    /* ------------------------- live form state ------------------------- */

    function currentModules() {
      return U.qsa('input[data-module]', moduleList).filter(function (cb) { return cb.checked; }).map(function (cb) { return cb.dataset.module; });
    }

    function refreshModuleCount() {
      updateEtaEstimate();
      var enabled = currentModules().length;
      if (moduleCountBadge) moduleCountBadge.textContent = enabled + ' enabled';
      if (summaryModules) summaryModules.textContent = enabled + ' / ' + totalModules;
    }

    function refreshSummaryTarget() {
      if (!summaryTarget) return;
      var value = urlInput.value.trim();
      summaryTarget.textContent = value ? U.hostnameOf(value) : '—';
    }

    function refreshDepthUi() {
      var isFull = !!(depthFull && depthFull.checked);
      if (summaryDepth) summaryDepth.textContent = isFull ? 'Entire website' : 'Homepage';
      if (maxPagesInput) maxPagesInput.disabled = !isFull;
      if (stepperMinus) stepperMinus.disabled = !isFull;
      if (stepperPlus) stepperPlus.disabled = !isFull;
      updateEtaEstimate();
    }

    function updateEtaEstimate() {
      var isFull = !!(depthFull && depthFull.checked);
      var pages = parseInt(maxPagesInput && maxPagesInput.value, 10) || 1;
      var minutes = isFull ? Math.max(1, Math.round(pages / 60)) : 1;
      if (currentModules().indexOf('journey') !== -1) minutes += isFull ? 4 : 2;  // live click-through of the journey
      if (summaryEta) summaryEta.textContent = '~' + minutes + ' min';
    }

    function refreshMaxPagesSummary() {
      if (summaryMaxPages) summaryMaxPages.textContent = maxPagesInput.value;
      updateEtaEstimate();
    }

    U.on(urlInput, 'input', function () {
      V.clearFieldState(urlWrap, urlError);
      refreshSummaryTarget();
    });
    U.on(urlInput, 'blur', function () { V.validateUrlField(urlInput, urlError) ? V.clearFieldState(urlWrap, urlError) : urlWrap.classList.add('is-invalid'); });

    [depthHomepage, depthFull].forEach(function (radio) {
      U.on(radio, 'change', refreshDepthUi);
    });

    U.on(stepperMinus, 'click', function () {
      var v = Math.max(1, (parseInt(maxPagesInput.value, 10) || 1) - 10);
      maxPagesInput.value = v;
      refreshMaxPagesSummary();
    });
    U.on(stepperPlus, 'click', function () {
      var v = Math.min(1000, (parseInt(maxPagesInput.value, 10) || 1) + 10);
      maxPagesInput.value = v;
      refreshMaxPagesSummary();
    });
    U.on(maxPagesInput, 'input', function () {
      maxPagesInput.value = maxPagesInput.value.replace(/[^\d]/g, '');
      refreshMaxPagesSummary();
    });

    U.qsa('input[data-module]', moduleList).forEach(function (cb) {
      U.on(cb, 'change', refreshModuleCount);
    });

    // Initialize summary values from current form state
    refreshSummaryTarget();
    refreshDepthUi();
    refreshModuleCount();

    /* ------------------------------ start audit ------------------------------ */

    U.on(startBtn, 'click', function () {
      var isValidUrl = V.validateUrlField(urlInput, urlError);
      if (!isValidUrl) {
        if (urlWrap) urlWrap.classList.add('is-invalid');
        urlInput.focus();
        return;
      }
      if (urlWrap) urlWrap.classList.remove('is-invalid');

      var modules = currentModules();
      if (!modules.length) {
        window.Notifications.warning('No modules selected', 'Enable at least one audit module to continue.');
        return;
      }

      var config = {
        url: urlInput.value.trim(),
        depth: (depthFull && depthFull.checked) ? 'full' : 'homepage',
        maxPages: parseInt(maxPagesInput.value, 10) || 1,
        modules: modules
      };
      var regionSelect = document.getElementById('targetRegionSelect');
      if (regionSelect && regionSelect.value && regionSelect.value !== 'auto') {
        config.targetRegion = regionSelect.value;
      }

      runAudit(config);
    });

    function runAudit(config) {
      window.Loader.setButtonLoading(startBtn, true, 'Starting…');
      if (progressSection) progressSection.style.display = '';
      if (checkList) checkList.style.display = '';
      if (taskEta) taskEta.style.display = '';
      if (progressHeading) progressHeading.textContent = 'Auditing ' + U.hostnameOf(config.url);
      var hostEl = document.getElementById('progressHost');
      if (hostEl) hostEl.textContent = U.hostnameOf(config.url);
      if (progressStatusText) progressStatusText.textContent = 'Starting…';
      resetChecklist();
      // Only show steps for the modules this audit actually runs.
      var STEP_MODULE = { checkConsent: 'consent', checkAnalytics: 'analytics', checkJourney: 'journey' };
      Object.keys(STEP_MODULE).forEach(function (id) {
        var row = document.getElementById(id);
        if (row) row.classList.toggle('is-skipped', (config.modules || []).indexOf(STEP_MODULE[id]) === -1);
      });
      document.body.style.overflow = 'hidden';

      var startedAt = Date.now();
      var elapsedEl = document.getElementById('runElapsed');
      var elapsedTimer = setInterval(function () {
        var s = Math.floor((Date.now() - startedAt) / 1000);
        if (elapsedEl) elapsedEl.textContent = Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
      }, 1000);
      function stopRunUi(hide) {
        clearInterval(elapsedTimer);
        if (hide) {
          if (progressSection) progressSection.style.display = 'none';
          document.body.style.overflow = '';
        }
      }

      window.Api.audits.run(config, function (progress) {
        updateProgressUi(progress, config);
      }).then(function (report) {
        stopRunUi(false);
        if (progressStatusText) progressStatusText.textContent = 'Audit complete — opening the report…';
        window.Notifications.success('Audit complete', U.hostnameOf(config.url) + ' scored ' + report.overall + '/100.');
        setTimeout(function () { window.location.href = 'report.html?id=' + encodeURIComponent(report.id); }, 900);
      }).catch(function (err) {
        stopRunUi(true);
        window.Loader.setButtonLoading(startBtn, false);
        window.Notifications.error('Audit failed', err.message || 'Something went wrong while auditing this site.');
      });
    }

    function resetChecklist() {
      CFG.AUDIT_STEPS.forEach(function (step) {
        setStepState(step.id, 'pending', 'pending');
      });
      U.setRingProgress(progressRingCircle, 0);
      if (progressPercentLabel) progressPercentLabel.textContent = '0';
      if (etaValue) etaValue.textContent = '—';
    }

    function setStepState(stepId, status, timeLabel) {
      var row = document.getElementById(stepId);
      if (!row) return;
      row.classList.remove('check-item--pass', 'check-item--warn', 'check-item--pending', 'check-item--fail');
      var icon = row.querySelector('.check-item__icon');
      var time = document.getElementById(stepId + 'Time');

      if (status === 'running') {
        row.classList.add('check-item--warn');
        if (icon) icon.innerHTML = '<span class="spinner"></span>';
        if (time) time.textContent = 'running…';
      } else if (status === 'pass') {
        row.classList.add('check-item--pass');
        if (icon) icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4L19 7"/></svg>';
        if (time) time.textContent = timeLabel || 'done';
      } else {
        row.classList.add('check-item--pending');
        if (icon) icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/></svg>';
        if (time) time.textContent = 'pending';
      }
    }

    function updateProgressUi(progress, config) {
      // 100% is reserved for a genuinely finished audit (status 'pass' =
      // backend status "completed"). Anything else — including an older
      // backend that still reports 100 while "Generating report" runs —
      // is capped at 95 so the ring never claims completion early.
      var isComplete = progress.status === 'pass';
      var shownPercent = isComplete ? 100 : Math.min(progress.percent, 95);

      U.setRingProgress(progressRingCircle, shownPercent);
      if (progressPercentLabel) progressPercentLabel.textContent = shownPercent;
      // Steps before the current one have finished: tick them off (the API
      // only reports the step that is running now).
      var ids = CFG.AUDIT_STEPS.map(function (s) { return s.id; });
      var at = ids.indexOf(progress.stepId);
      ids.forEach(function (id, i) {
        var row = document.getElementById(id);
        if (!row || row.classList.contains('check-item--pass')) return;
        if (isComplete || (at !== -1 && i < at)) setStepState(id, 'pass', 'done');
      });
      setStepState(progress.stepId, progress.status, progress.elapsedLabel);

      var stepMeta = CFG.AUDIT_STEPS.filter(function (s) { return s.id === progress.stepId; })[0];
      if (progressStatusText) {
        if (isComplete) {
          progressStatusText.textContent = 'Audit complete';
        } else if (stepMeta) {
          progressStatusText.textContent = progress.status === 'running'
            ? 'Running: ' + stepMeta.label + '…'
            : stepMeta.label + ' failed';
        }
      }

      var remainingPercent = 100 - shownPercent;
      // The Customer Journey module renders and clicks through pages in a real
      // browser, so it adds noticeably to the run time.
      var hasJourney = (config.modules || []).indexOf('journey') !== -1;
      var baseSeconds = (config.depth === 'full' ? 90 : 20) + (hasJourney ? (config.depth === 'full' ? 240 : 120) : 0);
      var etaSeconds = Math.max(3, Math.round((remainingPercent / 100) * baseSeconds));
      if (etaValue) etaValue.textContent = etaSeconds >= 60 ? Math.ceil(etaSeconds / 60) + ' min' : etaSeconds + ' sec';
    }
  });
})();
