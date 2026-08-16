/* ==========================================================================
   app.js — runs on every page. Wires up the shared app-shell chrome
   (sidebar, theme toggle, profile menu, notification bell) plus the
   settings.html page, which has no dedicated script file of its own.
   ========================================================================== */

(function () {
  var U = window.Utils;
  var CFG = window.APP_CONFIG;

  document.addEventListener('DOMContentLoaded', function () {
    applyStoredTheme();
    initSidebar();
    initThemeToggle();
    initProfileMenu();
    initNotificationBell();
    initSidebarLogout();
    highlightActiveNav();
    initSettingsPage();
    initRecurringAuditsSection();
  });

  /* ---------------------------------------------------------------- */
  /* Theme                                                              */
  /* ---------------------------------------------------------------- */

  function systemPrefersDark() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function applyTheme(mode) {
    var resolved = mode === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : mode;
    if (resolved === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
    else document.documentElement.removeAttribute('data-theme');

    U.qsa('.theme-toggle button').forEach(function (btn) {
      var isDarkBtn = /dark/i.test(btn.getAttribute('aria-label') || '');
      btn.classList.toggle('is-active', isDarkBtn === (resolved === 'dark'));
    });

    U.qsa('.theme-swatch').forEach(function (swatch) {
      swatch.classList.toggle('is-active', swatch.dataset.themeChoice === mode);
    });
  }

  function applyStoredTheme() {
    var mode = U.storageGet(CFG.STORAGE_KEYS.THEME, 'light');
    applyTheme(mode);
  }

  function initThemeToggle() {
    U.qsa('.theme-toggle button').forEach(function (btn) {
      U.on(btn, 'click', function () {
        var isDark = /dark/i.test(btn.getAttribute('aria-label') || '');
        var mode = isDark ? 'dark' : 'light';
        U.storageSet(CFG.STORAGE_KEYS.THEME, mode);
        applyTheme(mode);
      });
    });
  }

  /* ---------------------------------------------------------------- */
  /* Sidebar (mobile off-canvas)                                       */
  /* ---------------------------------------------------------------- */

  function initSidebar() {
    var sidebar = document.getElementById('sidebar');
    var backdrop = document.getElementById('sidebarBackdrop');
    var toggle = document.getElementById('menuToggle');
    if (!sidebar || !toggle) return;

    function openSidebar() {
      sidebar.classList.add('is-open');
      if (backdrop) backdrop.classList.add('is-open');
    }
    function closeSidebar() {
      sidebar.classList.remove('is-open');
      if (backdrop) backdrop.classList.remove('is-open');
    }

    U.on(toggle, 'click', function () {
      sidebar.classList.contains('is-open') ? closeSidebar() : openSidebar();
    });
    U.on(backdrop, 'click', closeSidebar);
    U.qsa('.sidebar__link').forEach(function (link) { U.on(link, 'click', closeSidebar); });
  }

  /* ---------------------------------------------------------------- */
  /* Active nav highlighting                                           */
  /* ---------------------------------------------------------------- */

  function highlightActiveNav() {
    var current = (location.pathname.split('/').pop() || 'index.html');
    U.qsa('.sidebar__link').forEach(function (link) {
      var href = (link.getAttribute('href') || '').split('#')[0];
      if (href && href === current) link.classList.add('is-active');
    });
  }

  /* ---------------------------------------------------------------- */
  /* Profile menu                                                       */
  /* ---------------------------------------------------------------- */

  function initProfileMenu() {
    var chip = U.qs('.profile-chip');
    if (!chip) return;

    var user = window.Api ? window.Api.auth.getUser() : null;
    var nameEl = chip.querySelector('.profile-chip__name');
    if (nameEl && user && user.name) nameEl.textContent = user.name.split(' ')[0];

    chip.style.cursor = 'pointer';
    chip.style.position = 'relative';

    var menu = null;
    function closeMenu() {
      if (menu && menu.parentNode) menu.parentNode.removeChild(menu);
      menu = null;
      document.removeEventListener('click', onDocClick);
    }
    function onDocClick(e) {
      if (!chip.contains(e.target)) closeMenu();
    }
    function openMenu() {
      menu = document.createElement('div');
      menu.style.cssText = 'position:absolute; right:0; top:calc(100% + 8px); background:var(--surface); ' +
        'border:1px solid var(--border); border-radius:var(--radius-md); box-shadow:var(--shadow-lg); ' +
        'min-width:180px; padding:6px; z-index:60; font-size:var(--fs-sm);';
      menu.innerHTML =
        '<div style="padding:8px 10px; color:var(--text-tertiary); font-size:12px;">' + U.escapeHtml((user && user.email) || '') + '</div>' +
        '<a href="settings.html" style="display:block; padding:8px 10px; border-radius:var(--radius-sm); color:var(--text-primary);">Settings</a>' +
        '<a href="#" id="profileMenuLogout" style="display:block; padding:8px 10px; border-radius:var(--radius-sm); color:var(--color-error);">Log out</a>';
      chip.appendChild(menu);
      U.qsa('a', menu).forEach(function (a) {
        U.on(a, 'mouseenter', function () { a.style.background = 'var(--surface-sunken)'; });
        U.on(a, 'mouseleave', function () { a.style.background = ''; });
      });
      U.on(menu.querySelector('#profileMenuLogout'), 'click', function (e) {
        e.preventDefault();
        if (window.Api) window.Api.auth.logout();
        window.location.href = 'login.html';
      });
      setTimeout(function () { document.addEventListener('click', onDocClick); }, 0);
    }

    U.on(chip, 'click', function () {
      menu ? closeMenu() : openMenu();
    });
  }

  /* ---------------------------------------------------------------- */
  /* Sidebar logout link                                                */
  /* ---------------------------------------------------------------- */

  function initSidebarLogout() {
    var link = document.getElementById('sidebarLogout');
    if (!link) return;

    U.on(link, 'click', function (e) {
      e.preventDefault();
      if (window.Api) window.Api.auth.logout();
      window.location.href = 'login.html';
    });
  }

  /* ---------------------------------------------------------------- */
  /* Notification bell                                                  */
  /* ---------------------------------------------------------------- */

  function initNotificationBell() {
    var bell = U.qs('.topbar__actions .icon-btn[aria-label="Notifications"]');
    if (!bell) return;

    bell.style.position = 'relative';
    var panel = null;

    function closePanel() {
      if (panel && panel.parentNode) panel.parentNode.removeChild(panel);
      panel = null;
      document.removeEventListener('click', onDocClick);
    }
    function onDocClick(e) {
      if (!bell.contains(e.target)) closePanel();
    }
    function openPanel() {
      var dot = bell.querySelector('.dot');
      if (dot) dot.style.display = 'none';

      panel = document.createElement('div');
      panel.style.cssText = 'position:absolute; right:0; top:calc(100% + 8px); background:var(--surface); ' +
        'border:1px solid var(--border); border-radius:var(--radius-md); box-shadow:var(--shadow-lg); ' +
        'width:280px; padding:10px; z-index:60;';
      // NOTE: there is no notifications backend endpoint yet (see
      // DEPLOYMENT_CHECKLIST.md "Add real notifications"). Rather than
      // showing fabricated audit results here, this is an honest empty
      // state until that endpoint exists.
      panel.innerHTML = '<div style="font-weight:700; font-size:var(--fs-sm); padding:6px 10px 10px;">Notifications</div>' +
        '<div style="padding:8px 10px; font-size:var(--fs-sm); color:var(--text-tertiary);">Notifications aren\'t set up yet. You\'ll see updates here once the notifications service is live.</div>';
      bell.appendChild(panel);
      setTimeout(function () { document.addEventListener('click', onDocClick); }, 0);
    }

    U.on(bell, 'click', function (e) {
      e.stopPropagation();
      panel ? closePanel() : openPanel();
    });
  }

  /* ---------------------------------------------------------------- */
  /* Settings page (no dedicated settings.js — wired here)              */
  /* ---------------------------------------------------------------- */

  function initSettingsPage() {
    var saveBtn = document.getElementById('saveSettingsBtn');
    if (!saveBtn || !window.Api) return; // not on settings.html

    var cancelBtn = document.getElementById('cancelSettingsBtn');
    var copyKeyBtn = document.getElementById('copyApiKeyBtn');
    var revokeKeyBtn = document.getElementById('revokeApiKeyBtn');
    var generateKeyBtn = document.getElementById('generateApiKeyBtn');
    var exportBtn = document.getElementById('exportDataBtn');
    var swatches = U.qsa('.theme-swatch');
    var apiKeyDisplay = document.getElementById('apiKeyDisplay');

    var selectedTheme = U.storageGet(CFG.STORAGE_KEYS.THEME, 'light');

    // Load persisted settings into the form
    window.Api.settings.get().then(function (s) {
      setVal('settingName', s.name);
      setVal('settingEmail', s.email);
      setVal('settingCompany', s.company);
      setVal('settingAiProvider', s.aiProvider);
      setChecked('notifyAuditCompleted', s.notifyAuditCompleted);
      setChecked('notifyCriticalIssue', s.notifyCriticalIssue);
      setChecked('notifyWeeklySummary', s.notifyWeeklySummary);
      setVal('settingLanguage', s.language);
      setVal('scheduleFrequency', s.scheduleFrequency);
      setVal('scheduleTime', s.scheduleTime);
      if (apiKeyDisplay && s.apiKey) apiKeyDisplay.textContent = maskKey(s.apiKey);
    });

    function setVal(id, value) {
      var el = document.getElementById(id);
      if (el && value != null) el.value = value;
    }
    function setChecked(id, value) {
      var el = document.getElementById(id);
      if (el) el.checked = !!value;
    }
    function getVal(id) {
      var el = document.getElementById(id);
      return el ? el.value : undefined;
    }
    function getChecked(id) {
      var el = document.getElementById(id);
      return el ? el.checked : undefined;
    }

    swatches.forEach(function (swatch) {
      U.on(swatch, 'click', function () {
        selectedTheme = swatch.dataset.themeChoice;
        swatches.forEach(function (s) { s.classList.toggle('is-active', s === swatch); });
        U.storageSet(CFG.STORAGE_KEYS.THEME, selectedTheme);
        applyTheme(selectedTheme);
      });
    });

    U.on(copyKeyBtn, 'click', function () {
      window.Api.settings.get().then(function (s) {
        U.copyToClipboard(s.apiKey).then(function () {
          window.Notifications.success('Copied', 'API key copied to clipboard.');
        });
      });
    });

    U.on(revokeKeyBtn, 'click', function () {
      window.Modal.confirm({
        title: 'Revoke production key?',
        body: 'Any integration using this key will stop working immediately. This can\'t be undone.',
        confirmLabel: 'Revoke key',
        dangerous: true,
        onConfirm: function () {
          window.Api.settings.regenerateApiKey().then(function (key) {
            if (apiKeyDisplay) apiKeyDisplay.textContent = maskKey(key);
            window.Notifications.warning('Key revoked', 'A new production key has been generated.');
          });
        }
      });
    });

    U.on(generateKeyBtn, 'click', function () {
      window.Loader.setButtonLoading(generateKeyBtn, true, 'Generating…');
      window.Api.settings.regenerateApiKey().then(function (key) {
        window.Loader.setButtonLoading(generateKeyBtn, false);
        if (apiKeyDisplay) apiKeyDisplay.textContent = maskKey(key);
        window.Notifications.success('New key generated', 'Copy it now — you won\'t see the full key again.');
      });
    });

    function maskKey(key) {
      return key.slice(0, 8) + '••••••••••••' + key.slice(-4);
    }

    U.on(exportBtn, 'click', function () {
      window.Api.settings.exportJson().then(function (data) {
        U.downloadTextFile('auditpulse-settings.json', JSON.stringify(data, null, 2), 'application/json');
        window.Notifications.info('Exported', 'Your workspace settings were downloaded as JSON.');
      });
    });

    U.on(cancelBtn, 'click', function (e) {
      e.preventDefault();
      window.location.reload();
    });

    U.on(saveBtn, 'click', function () {
      var patch = {
        name: getVal('settingName'),
        email: getVal('settingEmail'),
        company: getVal('settingCompany'),
        aiProvider: getVal('settingAiProvider'),
        notifyAuditCompleted: getChecked('notifyAuditCompleted'),
        notifyCriticalIssue: getChecked('notifyCriticalIssue'),
        notifyWeeklySummary: getChecked('notifyWeeklySummary'),
        theme: selectedTheme,
        language: getVal('settingLanguage'),
        scheduleFrequency: getVal('scheduleFrequency'),
        scheduleTime: getVal('scheduleTime')
      };

      if (patch.email && !window.Validation.isValidEmail(patch.email)) {
        window.Notifications.error('Invalid email', 'Please enter a valid profile email address.');
        return;
      }

      window.Loader.setButtonLoading(saveBtn, true, 'Saving…');
      window.Api.settings.save(patch).then(function () {
        window.Loader.setButtonLoading(saveBtn, false);
        window.Notifications.success('Settings saved', 'Your workspace preferences were updated.');
      });
    });
  }

  /* ---------------------------------------------------------------- */
  /* Recurring audits (settings.html "Recurring Audits" section)        */
  /* ---------------------------------------------------------------- */

  function initRecurringAuditsSection() {
    var listEl = document.getElementById('scheduleList');
    if (!listEl || !window.Api || !window.Api.scheduler) return; // not on settings.html

    var emptyEl = document.getElementById('scheduleListEmpty');
    var urlInput = document.getElementById('newScheduleUrl');
    var urlError = document.getElementById('newScheduleUrlError');
    var frequencyInput = document.getElementById('newScheduleFrequency');
    var dayInput = document.getElementById('newScheduleDay');
    var dayError = document.getElementById('newScheduleDayError');
    var timeInput = document.getElementById('newScheduleTime');
    var timeError = document.getElementById('newScheduleTimeError');
    var addBtn = document.getElementById('addScheduleBtn');

    function iconSvg() {
      return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
        'stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 3v6h6M12 7v5l4 2"/></svg>';
    }

    function metaLine(s) {
      var parts = [s.frequency, s.timeLabel];
      if (s.isActive && s.nextRunAt) parts.push('Next: ' + U.formatRelativeTime(s.nextRunAt));
      else if (!s.isActive) parts.push('Paused');
      if (s.lastRunAt) parts.push('Last ran ' + U.formatRelativeTime(s.lastRunAt));
      return parts.join(' · ');
    }

    function render(schedules) {
      listEl.innerHTML = '';
      if (!schedules.length) {
        if (emptyEl) emptyEl.style.display = '';
        return;
      }
      if (emptyEl) emptyEl.style.display = 'none';

      schedules.forEach(function (s) {
        var row = document.createElement('div');
        row.className = 'schedule-row' + (s.isActive ? '' : ' is-inactive');
        row.innerHTML =
          '<span class="schedule-row__icon">' + iconSvg() + '</span>' +
          '<div class="schedule-row__body">' +
            '<div class="schedule-row__url">' + U.escapeHtml(s.url) + '</div>' +
            '<div class="schedule-row__meta">' + U.escapeHtml(metaLine(s)) + '</div>' +
          '</div>' +
          '<div class="schedule-row__actions">' +
            '<label class="toggle" title="' + (s.isActive ? 'Pause' : 'Resume') + '">' +
              '<input type="checkbox" class="js-toggle-active"' + (s.isActive ? ' checked' : '') + '>' +
              '<span class="toggle__track"></span>' +
            '</label>' +
            '<button type="button" class="btn btn--secondary btn--sm js-run-now">Run now</button>' +
            '<button type="button" class="btn btn--danger btn--sm js-delete">Delete</button>' +
          '</div>';

        U.on(row.querySelector('.js-toggle-active'), 'change', function (e) {
          window.Api.scheduler.update(s.id, { isActive: e.target.checked }).then(function () {
            window.Notifications.info(e.target.checked ? 'Schedule resumed' : 'Schedule paused', s.url);
            load();
          }).catch(function (err) {
            e.target.checked = !e.target.checked; // revert on failure
            window.Notifications.error('Could not update schedule', err.message);
          });
        });

        U.on(row.querySelector('.js-run-now'), 'click', function (e) {
          var btn = e.currentTarget;
          window.Loader.setButtonLoading(btn, true, 'Starting…');
          window.Api.scheduler.runNow(s.id).then(function () {
            window.Notifications.success('Audit started', s.url + ' is being re-scanned now.');
            window.Loader.setButtonLoading(btn, false);
            load();
          }).catch(function (err) {
            window.Loader.setButtonLoading(btn, false);
            window.Notifications.error('Could not start audit', err.message);
          });
        });

        U.on(row.querySelector('.js-delete'), 'click', function () {
          window.Modal.confirm({
            title: 'Delete this recurring audit?',
            body: s.url + ' will no longer be scanned automatically. This can\'t be undone.',
            confirmLabel: 'Delete',
            dangerous: true,
            onConfirm: function () {
              window.Api.scheduler.remove(s.id).then(function () {
                window.Notifications.warning('Schedule deleted', s.url);
                load();
              }).catch(function (err) {
                window.Notifications.error('Could not delete schedule', err.message);
              });
            }
          });
        });

        listEl.appendChild(row);
      });
    }

    function load() {
      window.Api.scheduler.list().then(render).catch(function (err) {
        window.Notifications.error('Could not load recurring audits', err.message);
      });
    }

    U.on(addBtn, 'click', function () {
      var urlOk = window.Validation.validateUrlField(urlInput, urlError);
      urlInput.classList.toggle('is-invalid', !urlOk);
      
      // Validate frequency selection
      var frequencyOk = frequencyInput.value && frequencyInput.value !== '';
      if (!frequencyOk && frequencyInput) {
        if (!frequencyInput.classList) frequencyInput.classList = {};
        frequencyInput.classList.add('is-invalid');
      }
      
      // Validate day selection
      var dayOk = dayInput.value && dayInput.value !== '';
      dayInput.classList.toggle('is-invalid', !dayOk);
      if (!dayOk && dayError) dayError.textContent = 'Please select a day';
      
      // Validate time selection
      var timeOk = timeInput.value && timeInput.value !== '';
      timeInput.classList.toggle('is-invalid', !timeOk);
      if (!timeOk && timeError) timeError.textContent = 'Please select a time';
      
      if (!urlOk || !frequencyOk || !dayOk || !timeOk) return;

      // Format time label as "Day, HH:MM AM/PM"
      var timeStr = timeInput.value; // HH:MM format
      var timeParts = timeStr.split(':');
      var hour = parseInt(timeParts[0], 10);
      var minute = timeParts[1];
      var period = hour >= 12 ? 'PM' : 'AM';
      var displayHour = hour > 12 ? hour - 12 : (hour === 0 ? 12 : hour);
      var formattedTime = dayInput.value + ', ' + displayHour + ':' + minute + ' ' + period;

      window.Loader.setButtonLoading(addBtn, true, 'Adding…');
      window.Api.scheduler.create({
        url: urlInput.value.trim(),
        frequency: frequencyInput.value,
        timeLabel: formattedTime
      }).then(function () {
        window.Loader.setButtonLoading(addBtn, false);
        window.Notifications.success('Recurring audit added', urlInput.value.trim());
        urlInput.value = '';
        frequencyInput.value = '';
        dayInput.value = '';
        timeInput.value = '';
        window.Validation.clearFieldState(urlInput, urlError);
        if (dayError) dayError.textContent = '';
        if (timeError) timeError.textContent = '';
        load();
      }).catch(function (err) {
        window.Loader.setButtonLoading(addBtn, false);
        window.Notifications.error('Could not add recurring audit', err.message);
      });
    });

    U.on(urlInput, 'input', function () { window.Validation.clearFieldState(urlInput, urlError); });
    U.on(dayInput, 'change', function () { if (dayError) dayError.textContent = ''; dayInput.classList.remove('is-invalid'); });
    U.on(timeInput, 'change', function () { if (timeError) timeError.textContent = ''; timeInput.classList.remove('is-invalid'); });
    U.on(frequencyInput, 'change', function () { if (frequencyInput) frequencyInput.classList.remove('is-invalid'); });

    load();
  }

  // Exposed so settings.js-equivalent code above can call the same theme logic
  window.__applyTheme = applyTheme;
})();
