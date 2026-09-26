/* ==========================================================================
   audit.js — audit.html page logic: form state, module toggles,
   start-audit progress simulation, redirect to report.html on completion
   ========================================================================== */

(function () {
  var U = window.Utils;
  var V = window.Validation;
  var CFG = window.APP_CONFIG;

  // ------------------------------------------------------------------
  // Regional Information — client-side domain-only preview, shown the
  // moment a URL is typed, before the real audit runs. Mirrors a small
  // subset of the backend's consent.region_detector._COUNTRY_CODE_TABLE
  // (ccTLD -> country/framework); it is deliberately less thorough than
  // that module (no hreflang/lang/locale-path/selector/CMP/text signals,
  // since those need the crawled page), so it's always shown as a
  // "preliminary" guess and gets replaced by the backend's real,
  // multi-signal result once the audit's consent scan completes.
  // ------------------------------------------------------------------
  var REGION_TABLE = {
    FR: ['France', 'EU'], DE: ['Germany', 'EU'], IT: ['Italy', 'EU'], ES: ['Spain', 'EU'],
    BE: ['Belgium', 'EU'], IE: ['Ireland', 'EU'], NL: ['Netherlands', 'EU'], SE: ['Sweden', 'EU'],
    NO: ['Norway', 'EU'], DK: ['Denmark', 'EU'], FI: ['Finland', 'EU'], AT: ['Austria', 'EU'],
    PT: ['Portugal', 'EU'], PL: ['Poland', 'EU'], CZ: ['Czechia', 'EU'], RO: ['Romania', 'EU'],
    GR: ['Greece', 'EU'], HU: ['Hungary', 'EU'], LU: ['Luxembourg', 'EU'], MT: ['Malta', 'EU'],
    IS: ['Iceland', 'EU'], LI: ['Liechtenstein', 'EU'],
    UK: ['United Kingdom', 'UK'], GB: ['United Kingdom', 'UK'],
    CH: ['Switzerland', 'CH'],
    US: ['United States', 'US']
  };
  var REGION_FRAMEWORK_NAME = { EU: 'GDPR', UK: 'UK GDPR', CH: 'Swiss FADP', 'US-CA': 'CCPA/CPRA', US: null, UNKNOWN: null };
  var REGION_FLAG = {
    EU: '🇪🇺', UK: '🇬🇧', CH: '🇨🇭', 'US-CA': '🇺🇸', US: '🇺🇸', UNKNOWN: '🌐',
    France: '🇫🇷', Germany: '🇩🇪', Italy: '🇮🇹', Spain: '🇪🇸', Belgium: '🇧🇪', Ireland: '🇮🇪',
    Netherlands: '🇳🇱', Sweden: '🇸🇪', Norway: '🇳🇴', Denmark: '🇩🇰', Finland: '🇫🇮', Austria: '🇦🇹',
    Portugal: '🇵🇹', Poland: '🇵🇱', Czechia: '🇨🇿', Romania: '🇷🇴', Greece: '🇬🇷', Hungary: '🇭🇺',
    Luxembourg: '🇱🇺', Malta: '🇲🇹', Iceland: '🇮🇸', Liechtenstein: '🇱🇮',
    'United Kingdom': '🇬🇧', Switzerland: '🇨🇭', 'United States': '🇺🇸', California: '🇺🇸'
  };
  var REGION_OVERRIDE_LABEL = {
    EU: ['European Union', 'GDPR'], UK: ['United Kingdom', 'UK GDPR'], CH: ['Switzerland', 'Swiss FADP'],
    'US-CA': ['California', 'CCPA/CPRA'], US: ['United States', null], UNKNOWN: ['Unknown', null]
  };

  function quickDomainRegionGuess(url) {
    var host;
    try { host = new URL(/^https?:\/\//i.test(url) ? url : 'https://' + url).hostname.toLowerCase(); }
    catch (e) { return null; }
    if (!host) return null;
    if (host.endsWith('.co.uk') || host.endsWith('.uk')) {
      return { country: 'United Kingdom', bucket: 'UK', confidence: 'low', source: 'Domain (preliminary)' };
    }
    var tld = host.split('.').pop().toUpperCase();
    var hit = REGION_TABLE[tld];
    if (!hit) return null;
    return { country: hit[0], bucket: hit[1], confidence: 'low', source: 'Domain (preliminary)' };
  }

  document.addEventListener('DOMContentLoaded', function () {
    var urlInput = document.getElementById('auditUrlInput');
    if (!urlInput || !window.Api) return; // not on audit.html

    /* ------------------------- Regional Information card ------------------------- */

    var regionInfoPlaceholder = document.getElementById('regionInfoPlaceholder');
    var regionInfoBody = document.getElementById('regionInfoBody');
    var regionInfoUrl = document.getElementById('regionInfoUrl');
    var regionInfoFlag = document.getElementById('regionInfoFlag');
    var regionInfoRegion = document.getElementById('regionInfoRegion');
    var regionInfoFramework = document.getElementById('regionInfoFramework');
    var regionInfoConfidence = document.getElementById('regionInfoConfidence');
    var regionInfoSource = document.getElementById('regionInfoSource');
    var regionInfoNote = document.getElementById('regionInfoNote');
    var regionModeBadge = document.getElementById('regionModeBadge');
    var regionAdvancedToggle = document.getElementById('regionAdvancedToggle');
    var regionAdvanced = document.getElementById('regionAdvanced');
    var regionOverrideSelect = document.getElementById('regionOverrideSelect');

    var lastDetected = null; // { country, framework, confidence, source, note }

    function renderRegionCard() {
      var value = urlInput.value.trim();
      var overrideCode = regionOverrideSelect ? regionOverrideSelect.value : 'auto';

      if (regionModeBadge) {
        regionModeBadge.textContent = overrideCode === 'auto' ? 'Auto Detect' : 'Manual Override';
        regionModeBadge.className = 'badge ' + (overrideCode === 'auto' ? 'badge--neutral' : 'badge--warning');
      }

      if (overrideCode !== 'auto') {
        var meta = REGION_OVERRIDE_LABEL[overrideCode] || ['Unknown', null];
        showRegionData({
          country: meta[0],
          framework: meta[1],
          confidence: 'override',
          source: 'Manually set (internal use)',
          note: 'This is a manual override for internal review — it does not change the real audit, only what\u2019s shown here.'
        });
        return;
      }

      if (lastDetected) {
        showRegionData(lastDetected);
      } else if (value) {
        var guess = quickDomainRegionGuess(value);
        if (guess) {
          showRegionData({
            country: guess.country,
            framework: REGION_FRAMEWORK_NAME[guess.bucket] || null,
            confidence: guess.confidence,
            source: guess.source,
            note: 'Preliminary guess from the domain only — the full audit also checks hreflang tags, page language, locale paths and on-page text for a more confident result.'
          });
        } else {
          hideRegionData();
        }
      } else {
        hideRegionData();
      }
    }

    function showRegionData(data) {
      if (regionInfoPlaceholder) regionInfoPlaceholder.style.display = 'none';
      if (regionInfoBody) regionInfoBody.classList.add('is-visible');
      if (regionInfoUrl) regionInfoUrl.textContent = urlInput.value.trim() ? U.hostnameOf(urlInput.value.trim()) : '—';
      if (regionInfoFlag) regionInfoFlag.textContent = REGION_FLAG[data.country] || '🌐';
      if (regionInfoRegion) regionInfoRegion.textContent = data.country || 'Unknown';
      if (regionInfoFramework) regionInfoFramework.textContent = data.framework || 'None applicable';
      if (regionInfoConfidence) {
        var conf = data.confidence || 'none';
        regionInfoConfidence.textContent = conf === 'override' ? 'Override' : conf.charAt(0).toUpperCase() + conf.slice(1);
        regionInfoConfidence.className = 'region-info-confidence region-info-confidence--' + conf;
      }
      if (regionInfoSource) regionInfoSource.textContent = data.source || 'None';
      if (regionInfoNote) regionInfoNote.textContent = data.note || '';
    }

    function hideRegionData() {
      if (regionInfoPlaceholder) regionInfoPlaceholder.style.display = '';
      if (regionInfoBody) regionInfoBody.classList.remove('is-visible');
    }

    U.on(urlInput, 'input', renderRegionCard);
    if (regionOverrideSelect) U.on(regionOverrideSelect, 'change', renderRegionCard);
    if (regionAdvancedToggle && regionAdvanced) {
      U.on(regionAdvancedToggle, 'click', function () {
        regionAdvanced.classList.toggle('is-visible');
      });
    }
    renderRegionCard();

    /* ------------------------------------------------------------------ */

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

      runAudit(config);
    });

    function runAudit(config) {
      window.Loader.setButtonLoading(startBtn, true, 'Starting…');
      if (progressSection) progressSection.style.display = '';
      if (checkList) checkList.style.display = '';
      if (taskEta) taskEta.style.display = '';
      if (progressHeading) progressHeading.textContent = 'Analyzing ' + U.hostnameOf(config.url);
      if (progressStatusText) progressStatusText.textContent = 'Starting…';
      resetChecklist();

      var startedAt = Date.now();

      window.Api.audits.run(config, function (progress) {
        updateProgressUi(progress, config);
      }).then(function (report) {
        if (progressStatusText) progressStatusText.textContent = 'Audit complete — redirecting to report…';
        window.Notifications.success('Audit complete', U.hostnameOf(config.url) + ' scored ' + report.overall + '/100.');
        // Swap the domain-only preview for the backend's real, multi-signal
        // region detection (consent.region_detector) now that the crawl +
        // consent scan have actually run — best-effort: if this fails or
        // the redirect fires first, the preview simply stays as-is.
        if (config.modules.indexOf('consent') !== -1 && window.Api.audits.getConsent) {
          window.Api.audits.getConsent(report.id).then(function (consent) {
            if (!consent) return;
            lastDetected = {
              country: consent.detectedCountry || (consent.detectedRegion === 'UNKNOWN' ? 'Unknown' : consent.detectedRegion),
              framework: consent.complianceFramework || null,
              confidence: consent.regionConfidence || 'none',
              source: consent.regionDetectionSource || 'None',
              note: consent.regionDetectionReason || 'Detected from the crawled page — domain, hreflang, page language, locale path, and on-page signals.'
            };
            renderRegionCard();
          }).catch(function () { /* keep the preview shown — not worth surfacing an error here */ });
        }
        setTimeout(function () { window.location.href = 'report.html?id=' + encodeURIComponent(report.id); }, 900);
      }).catch(function (err) {
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
      var etaSeconds = Math.max(3, Math.round((remainingPercent / 100) * (config.depth === 'full' ? 90 : 20)));
      if (etaValue) etaValue.textContent = etaSeconds >= 60 ? Math.ceil(etaSeconds / 60) + ' min' : etaSeconds + ' sec';
    }
  });
})();
