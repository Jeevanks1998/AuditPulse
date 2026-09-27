/* ==========================================================================
   settings.js — settings.html page logic.

   Loads the signed-in user's profile + preferences from window.Api.settings
   (backend/api/settings.py), fills the form, and saves changes back with a
   PATCH containing only the fields that actually changed. Also handles the
   theme swatches, API-key show/copy/regenerate, and the JSON data export.

   Backend note: reading settings works for every role, but saving,
   regenerating the API key and exporting are gated to the "settings"
   module (Admin only — see backend/config/permissions.py). For other
   roles those calls come back 403 and the message is shown as a toast.
   ========================================================================== */

(function () {
  var U = window.Utils;
  var V = window.Validation;

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('settingsForm');
    if (!form || !window.Api || !U) return; // not on settings.html

    var $ = function (id) { return document.getElementById(id); };

    var els = {
      name: $('settingsName'),
      email: $('settingsEmail'),
      company: $('settingsCompany'),
      aiProvider: $('settingsAiProvider'),
      notifyAuditCompleted: $('settingsNotifyAuditCompleted'),
      notifyCriticalIssue: $('settingsNotifyCriticalIssue'),
      notifyWeeklySummary: $('settingsNotifyWeeklySummary'),
      language: $('settingsLanguage'),
      scheduleFrequency: $('settingsScheduleFrequency'),
      scheduleTime: $('settingsScheduleTime')
    };
    var swatches = U.qsa('[data-theme-choice]', $('settingsThemeSwatches'));
    var saveBtn = $('settingsSaveBtn');
    var resetBtn = $('settingsResetBtn');
    var apiKeyEl = $('settingsApiKey');
    var apiKeyToggle = $('settingsApiKeyToggle');
    var apiKeyCopy = $('settingsApiKeyCopy');
    var apiKeyRegen = $('settingsApiKeyRegen');
    var exportBtn = $('settingsExportBtn');

    var THEME_KEY = (window.APP_CONFIG && window.APP_CONFIG.STORAGE_KEYS && window.APP_CONFIG.STORAGE_KEYS.THEME) || 'auditpulse:theme';

    var loaded = null;      // last values received from / saved to the server
    var theme = 'light';    // current swatch selection
    var apiKey = '';
    var apiKeyVisible = false;

    /* ------------------------------ helpers ------------------------------ */

    // A <select> can only show options it has. If the account holds a value
    // this page doesn't list (e.g. a provider chosen elsewhere), add it so
    // saving doesn't silently overwrite it with the first option.
    function setSelect(select, value) {
      if (value == null || value === '') return;
      var has = Array.prototype.some.call(select.options, function (o) { return o.value === value; });
      if (!has) {
        var opt = document.createElement('option');
        opt.value = value;
        opt.textContent = value;
        select.appendChild(opt);
      }
      select.value = value;
    }

    function maskKey(key) {
      if (!key) return '—';
      if (key.length <= 8) return key;
      return key.slice(0, 8) + new Array(Math.max(key.length - 12, 4) + 1).join('•') + key.slice(-4);
    }

    function renderApiKey() {
      apiKeyEl.textContent = apiKeyVisible ? (apiKey || '—') : maskKey(apiKey);
      apiKeyToggle.textContent = apiKeyVisible ? 'Hide' : 'Show';
      apiKeyToggle.disabled = apiKeyCopy.disabled = apiKeyRegen.disabled = !apiKey;
    }

    /* -------------------------------- theme ------------------------------- */

    function applyTheme(choice) {
      var dark = choice === 'dark' ||
        (choice === 'system' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
      if (dark) document.documentElement.setAttribute('data-theme', 'dark');
      else document.documentElement.removeAttribute('data-theme');

      // Keep the topbar light/dark buttons in step.
      var toggle = document.querySelector('.theme-toggle');
      if (toggle) {
        var lightBtn = toggle.querySelector('[aria-label="Light mode"]');
        var darkBtn = toggle.querySelector('[aria-label="Dark mode"]');
        if (lightBtn) lightBtn.classList.toggle('is-active', !dark);
        if (darkBtn) darkBtn.classList.toggle('is-active', dark);
      }

      // The topbar toggle only knows light/dark. "System" is stored as
      // "no explicit choice" so app.js falls back to the OS preference.
      if (choice === 'system') U.storageRemove(THEME_KEY);
      else U.storageSet(THEME_KEY, choice);
    }

    function setThemeSelection(choice, apply) {
      theme = choice;
      swatches.forEach(function (s) {
        var on = s.getAttribute('data-theme-choice') === choice;
        s.classList.toggle('is-active', on);
        s.setAttribute('aria-checked', on ? 'true' : 'false');
      });
      if (apply) applyTheme(choice);
      updateDirty();
    }

    swatches.forEach(function (s) {
      var pick = function () { setThemeSelection(s.getAttribute('data-theme-choice'), true); };
      U.on(s, 'click', pick);
      U.on(s, 'keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
      });
    });

    /* ----------------------------- form <-> data ---------------------------- */

    function readForm() {
      return {
        name: els.name.value.trim(),
        email: els.email.value.trim(),
        company: els.company.value.trim(),
        aiProvider: els.aiProvider.value,
        notifyAuditCompleted: els.notifyAuditCompleted.checked,
        notifyCriticalIssue: els.notifyCriticalIssue.checked,
        notifyWeeklySummary: els.notifyWeeklySummary.checked,
        theme: theme,
        language: els.language.value,
        scheduleFrequency: els.scheduleFrequency.value,
        scheduleTime: els.scheduleTime.value.trim()
      };
    }

    function fillForm(s) {
      els.name.value = s.name || '';
      els.email.value = s.email || '';
      els.company.value = s.company || '';
      setSelect(els.aiProvider, s.aiProvider);
      els.notifyAuditCompleted.checked = !!s.notifyAuditCompleted;
      els.notifyCriticalIssue.checked = !!s.notifyCriticalIssue;
      els.notifyWeeklySummary.checked = !!s.notifyWeeklySummary;
      setSelect(els.language, s.language);
      setSelect(els.scheduleFrequency, s.scheduleFrequency);
      els.scheduleTime.value = s.scheduleTime || '';
      setThemeSelection(s.theme || 'light', false);
      apiKey = s.apiKey || '';
      renderApiKey();
      Object.keys(els).forEach(function (k) { els[k].classList.remove('is-invalid'); });
    }

    function changedFields() {
      if (!loaded) return {};
      var now = readForm();
      var patch = {};
      Object.keys(now).forEach(function (k) {
        if (now[k] !== loaded[k]) patch[k] = now[k];
      });
      return patch;
    }

    function updateDirty() {
      saveBtn.disabled = !loaded || Object.keys(changedFields()).length === 0;
    }

    Object.keys(els).forEach(function (k) {
      var ev = (els[k].type === 'checkbox' || els[k].tagName === 'SELECT') ? 'change' : 'input';
      U.on(els[k], ev, updateDirty);
    });

    /* -------------------------------- load --------------------------------- */

    function load() {
      saveBtn.disabled = true;
      return window.Api.settings.get()
        .then(function (s) {
          loaded = {
            name: s.name || '',
            email: s.email || '',
            company: s.company || '',
            aiProvider: s.aiProvider,
            notifyAuditCompleted: !!s.notifyAuditCompleted,
            notifyCriticalIssue: !!s.notifyCriticalIssue,
            notifyWeeklySummary: !!s.notifyWeeklySummary,
            theme: s.theme || 'light',
            language: s.language,
            scheduleFrequency: s.scheduleFrequency,
            scheduleTime: s.scheduleTime || ''
          };
          fillForm(s);
          // Settings are the source of truth for the theme; carry them to
          // this browser (e.g. a new device) without waiting for a click.
          applyTheme(loaded.theme);
          updateDirty();
        })
        .catch(function (err) {
          window.Notifications.error('Couldn\u2019t load your settings', (err && err.message) || 'Please refresh the page to try again.');
        });
    }

    /* -------------------------------- save --------------------------------- */

    function validate(patch) {
      var ok = true;
      if ('name' in patch && !patch.name) {
        els.name.classList.add('is-invalid'); els.name.focus(); ok = false;
      } else {
        els.name.classList.remove('is-invalid');
      }
      if ('email' in patch && !V.isValidEmail(patch.email)) {
        els.email.classList.add('is-invalid');
        if (ok) els.email.focus();
        ok = false;
      } else {
        els.email.classList.remove('is-invalid');
      }
      return ok;
    }

    U.on(saveBtn, 'click', function () {
      var patch = changedFields();
      if (!Object.keys(patch).length) return;
      if (!validate(patch)) {
        window.Notifications.warning('Check your details', 'Name can\u2019t be empty and the email must be valid.');
        return;
      }

      window.Loader.setButtonLoading(saveBtn, true, 'Saving…');
      window.Api.settings.save(patch)
        .then(function (s) {
          Object.keys(patch).forEach(function (k) { loaded[k] = patch[k]; });
          if (s && s.apiKey) { apiKey = s.apiKey; renderApiKey(); }

          // Reflect a new name in the topbar chip straight away.
          if ('name' in patch) {
            var nameEl = document.querySelector('.profile-chip__name');
            if (nameEl) nameEl.textContent = patch.name;
          }
          if (window.Api.auth.verifySession) window.Api.auth.verifySession().catch(function () {});

          window.Notifications.success('Settings saved', 'Your changes have been applied.');
        })
        .catch(function (err) {
          window.Notifications.error('Couldn\u2019t save your settings', (err && err.message) || 'Please try again.');
        })
        .then(function () {
          window.Loader.setButtonLoading(saveBtn, false);
          updateDirty();
        });
    });

    U.on(resetBtn, 'click', function () {
      if (!loaded) return;
      fillForm(Object.assign({ apiKey: apiKey }, loaded));
      applyTheme(loaded.theme);
      updateDirty();
    });

    /* ------------------------------- API key ------------------------------- */

    U.on(apiKeyToggle, 'click', function () {
      apiKeyVisible = !apiKeyVisible;
      renderApiKey();
    });

    U.on(apiKeyCopy, 'click', function () {
      if (!apiKey) return;
      U.copyToClipboard(apiKey)
        .then(function () { window.Notifications.success('API key copied', 'Paste it wherever you need it.'); })
        .catch(function () { window.Notifications.error('Couldn\u2019t copy', 'Show the key and copy it manually.'); });
    });

    U.on(apiKeyRegen, 'click', function () {
      window.Modal.confirm({
        title: 'Regenerate API key?',
        body: 'Your current key stops working immediately. Anything still using it will need the new key.',
        confirmLabel: 'Regenerate',
        dangerous: true,
        onConfirm: function () {
          window.Api.settings.regenerateApiKey()
            .then(function (key) {
              apiKey = key;
              apiKeyVisible = true;
              renderApiKey();
              window.Notifications.success('New API key generated', 'The previous key no longer works.');
            })
            .catch(function (err) {
              window.Notifications.error('Couldn\u2019t regenerate the key', (err && err.message) || 'Please try again.');
            });
        }
      });
    });

    /* -------------------------------- export ------------------------------- */

    U.on(exportBtn, 'click', function () {
      window.Loader.setButtonLoading(exportBtn, true, 'Preparing…');
      window.Api.settings.exportJson()
        .then(function (data) {
          var stamp = new Date().toISOString().slice(0, 10);
          U.downloadTextFile('auditpulse-export-' + stamp + '.json', JSON.stringify(data, null, 2), 'application/json');
          window.Notifications.success('Export ready', 'Your data has been downloaded.');
        })
        .catch(function (err) {
          window.Notifications.error('Couldn\u2019t export your data', (err && err.message) || 'Please try again.');
        })
        .then(function () { window.Loader.setButtonLoading(exportBtn, false); });
    });

    /* ------------------------- section nav highlight ------------------------ */

    var navLinks = U.qsa('.settings-nav a');
    navLinks.forEach(function (link) {
      U.on(link, 'click', function () {
        navLinks.forEach(function (l) { l.classList.toggle('is-active', l === link); });
      });
    });

    load();
  });
})();
