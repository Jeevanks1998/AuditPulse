/* ==========================================================================
   scheduler.js — scheduler.html page logic. Fetches/creates/updates
   recurring audit schedules via window.Api.scheduler (assets/js/api.js,
   which talks to backend/api/scheduler.py), and renders them into the
   summary stat cards + #scheduleTableBody.
   ========================================================================== */

(function () {
  var U = window.Utils;
  var V = window.Validation;

  document.addEventListener('DOMContentLoaded', function () {
    var tableBody = document.getElementById('scheduleTableBody');
    if (!tableBody || !window.Api || !window.Components) return; // not on scheduler.html

    var countLabel = document.querySelector('[data-schedule-table-count]');
    var emptyState = document.getElementById('scheduleTableEmpty');
    var table = document.getElementById('scheduleTable');
    var searchInput = document.getElementById('schedulerSearchInput');

    var statActive = document.getElementById('statActiveSchedules');
    var statUpcoming = document.getElementById('statUpcomingRuns');
    var statTotal = document.getElementById('statTotalScheduled');
    var statPaused = document.getElementById('statPausedSchedules');

    var allSchedules = [];

    load();

    document.getElementById('scheduleAuditBtn').addEventListener('click', function () {
      openScheduleModal(null);
    });
    var emptyBtn = document.getElementById('scheduleAuditEmptyBtn');
    if (emptyBtn) emptyBtn.addEventListener('click', function () { openScheduleModal(null); });

    if (searchInput) {
      searchInput.addEventListener('input', function () {
        var q = searchInput.value.trim().toLowerCase();
        if (!q) { render(allSchedules); return; }
        render(allSchedules.filter(function (s) {
          return U.hostnameOf(s.url).toLowerCase().indexOf(q) !== -1;
        }));
      });
    }

    // Close any open row action menu when clicking elsewhere on the page.
    document.addEventListener('click', function (e) {
      U.qsa('.action-menu.is-open').forEach(function (menu) {
        if (!menu.contains(e.target)) menu.classList.remove('is-open');
      });
    });

    tableBody.addEventListener('click', function (e) {
      var toggle = e.target.closest('[data-action-toggle]');
      if (toggle) {
        var menu = toggle.closest('.action-menu');
        var wasOpen = menu.classList.contains('is-open');
        U.qsa('.action-menu.is-open').forEach(function (m) { m.classList.remove('is-open'); });
        if (!wasOpen) menu.classList.add('is-open');
        return;
      }

      var actionBtn = e.target.closest('[data-schedule-action]');
      if (!actionBtn) return;
      var id = actionBtn.getAttribute('data-schedule-id');
      var action = actionBtn.getAttribute('data-schedule-action');
      var schedule = allSchedules.filter(function (s) { return String(s.id) === String(id); })[0];
      if (!schedule) return;

      U.qsa('.action-menu.is-open').forEach(function (m) { m.classList.remove('is-open'); });

      if (action === 'run-now') runNow(schedule);
      else if (action === 'edit') openScheduleModal(schedule);
      else if (action === 'pause' || action === 'resume') toggleActive(schedule);
      else if (action === 'delete') confirmDelete(schedule);
    });

    /* ------------------------------ data ------------------------------ */

    function load() {
      tableBody.innerHTML = '<tr><td colspan="7" class="text-tertiary">Loading schedules…</td></tr>';
      return window.Api.scheduler.list()
        .then(function (list) {
          allSchedules = list || [];
          render(allSchedules);
        })
        .catch(function () {
          tableBody.innerHTML = '';
          window.Notifications.error('Couldn\'t load schedules', 'Please refresh the page to try again.');
        });
    }

    function render(list) {
      renderStats(allSchedules);

      if (countLabel) {
        countLabel.textContent = list.length + (list.length === 1 ? ' schedule' : ' schedules');
      }

      if (!list.length) {
        tableBody.innerHTML = '';
        if (table) table.style.display = 'none';
        if (emptyState) emptyState.style.display = 'block';
        return;
      }

      if (table) table.style.display = '';
      if (emptyState) emptyState.style.display = 'none';

      tableBody.innerHTML = list.map(renderRow).join('');
    }

    function renderStats(list) {
      var active = list.filter(function (s) { return s.isActive; });
      var paused = list.filter(function (s) { return !s.isActive; });
      var upcoming = list.filter(function (s) { return s.isActive && s.nextRunAt; }).length;

      if (statActive) statActive.textContent = active.length;
      if (statUpcoming) statUpcoming.textContent = upcoming;
      if (statTotal) statTotal.textContent = list.length;
      if (statPaused) statPaused.textContent = paused.length;
    }

    function renderRow(s) {
      var host = U.hostnameOf(s.url);
      var statusHtml = s.isActive
        ? '<span class="badge badge--success schedule-status"><span class="schedule-status__dot schedule-status__dot--active"></span>Active</span>'
        : '<span class="badge badge--neutral schedule-status"><span class="schedule-status__dot schedule-status__dot--paused"></span>Paused</span>';

      return (
        '<tr>' +
          '<td>' +
            '<div style="display:flex; align-items:center; gap:10px;">' +
              '<div class="row-item__favicon">' + U.escapeHtml(U.faviconLetter(s.url)) + '</div>' +
              '<span>' + U.escapeHtml(host) + '</span>' +
            '</div>' +
          '</td>' +
          '<td>' + U.escapeHtml(s.frequency) + '</td>' +
          '<td class="text-tertiary">' + U.escapeHtml(s.timeLabel || '—') + '</td>' +
          '<td class="text-tertiary">' + shortDate(s.nextRunAt) + '</td>' +
          '<td class="text-tertiary">' + shortDate(s.lastRunAt) + '</td>' +
          '<td>' + statusHtml + '</td>' +
          '<td>' +
            '<div class="action-menu">' +
              '<button type="button" class="icon-btn" data-action-toggle aria-label="Schedule actions">' +
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>' +
              '</button>' +
              '<div class="action-menu__dropdown">' +
                '<button type="button" class="action-menu__item" data-schedule-action="run-now" data-schedule-id="' + s.id + '">' +
                  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 3 14 9-14 9V3Z"/></svg>Run Now</button>' +
                '<button type="button" class="action-menu__item" data-schedule-action="edit" data-schedule-id="' + s.id + '">' +
                  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4Z"/></svg>Edit</button>' +
                '<button type="button" class="action-menu__item" data-schedule-action="' + (s.isActive ? 'pause' : 'resume') + '" data-schedule-id="' + s.id + '">' +
                  (s.isActive
                    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>Pause'
                    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 3 14 9-14 9V3Z"/></svg>Resume') +
                '</button>' +
                '<button type="button" class="action-menu__item action-menu__item--danger" data-schedule-action="delete" data-schedule-id="' + s.id + '">' +
                  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6"/></svg>Delete</button>' +
              '</div>' +
            '</div>' +
          '</td>' +
        '</tr>'
      );
    }

    function shortDate(iso) {
      if (!iso) return '—';
      var d = new Date(iso);
      if (isNaN(d.getTime())) return '—';
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }

    /* ------------------------------ actions ------------------------------ */

    function runNow(schedule) {
      window.Api.scheduler.runNow(schedule.id)
        .then(function () {
          window.Notifications.success('Audit started', U.hostnameOf(schedule.url) + ' is being audited now — check History for progress.');
          load();
        })
        .catch(function (err) {
          window.Notifications.error('Couldn\'t start the audit', err.message);
        });
    }

    function toggleActive(schedule) {
      var willBeActive = !schedule.isActive;
      window.Api.scheduler.update(schedule.id, { isActive: willBeActive })
        .then(function () {
          window.Notifications.success(willBeActive ? 'Schedule resumed' : 'Schedule paused', U.hostnameOf(schedule.url));
          load();
        })
        .catch(function (err) {
          window.Notifications.error('Couldn\'t update the schedule', err.message);
        });
    }

    function confirmDelete(schedule) {
      window.Modal.confirm({
        title: 'Delete this schedule?',
        body: 'This stops all future recurring audits for ' + U.hostnameOf(schedule.url) + '. This can\'t be undone.',
        confirmLabel: 'Delete',
        dangerous: true,
        onConfirm: function () {
          window.Api.scheduler.remove(schedule.id)
            .then(function () {
              window.Notifications.success('Schedule deleted', U.hostnameOf(schedule.url) + ' will no longer run automatically.');
              load();
            })
            .catch(function (err) {
              window.Notifications.error('Couldn\'t delete the schedule', err.message);
            });
        }
      });
    }

    /* ------------------------------ create/edit modal ------------------------------ */

    var FREQUENCIES = ['Daily', 'Weekly', 'Monthly', 'Yearly'];
    var WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    // A short, practical list — not exhaustive IANA coverage — covering the
    // zones AuditPulse's userbase is most likely to be in.
    var TIMEZONES = [
      'UTC', 'Asia/Kolkata', 'Asia/Dubai', 'Asia/Singapore', 'Asia/Tokyo', 'Asia/Shanghai',
      'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Moscow',
      'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'America/Sao_Paulo',
      'Australia/Sydney', 'Pacific/Auckland'
    ];

    function detectTimezone() {
      try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Kolkata';
      } catch (e) {
        return 'Asia/Kolkata';
      }
    }

    function pad2(n) { return (n < 10 ? '0' : '') + n; }

    function todayIso() {
      var d = new Date();
      return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
    }

    function isoPlusYear(iso) {
      var d = new Date(iso + 'T00:00:00');
      if (isNaN(d.getTime())) d = new Date();
      d.setFullYear(d.getFullYear() + 1);
      return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
    }

    function ordinal(n) {
      n = Number(n);
      var s = ['th', 'st', 'nd', 'rd'], v = n % 100;
      return n + (s[(v - 20) % 10] || s[v] || s[0]);
    }

    function selectOptions(values, selected, labelFn) {
      return values.map(function (v) {
        return '<option value="' + U.escapeHtml(v) + '"' + (String(v) === String(selected) ? ' selected' : '') + '>' +
          U.escapeHtml(labelFn ? labelFn(v) : v) + '</option>';
      }).join('');
    }

    var MODULES = [
      { id: 'performance', label: 'Performance' },
      { id: 'accessibility', label: 'Accessibility' },
      { id: 'analytics', label: 'Analytics' },
      { id: 'consent', label: 'Consent' },
      { id: 'security', label: 'Security' }
    ];

    function openScheduleModal(existing) {
      var isEdit = !!existing;

      // Sensible defaults, or carry over an existing schedule's config if present.
      var cfg = (existing && existing.config) || {};
      var state = {
        frequency: (existing && existing.frequency) || 'Weekly',
        time: cfg.time || '09:00 AM',
        timezone: cfg.timezone || detectTimezone(),
        weekday: cfg.weekday || 'Monday',
        monthDay: cfg.monthDay || 15,
        monthDayMode: cfg.monthDayMode || 'specific', // 'specific' | 'last'
        yearMonth: cfg.yearMonth || 'September',
        yearDay: cfg.yearDay || 15,
        startDate: cfg.startDate || todayIso(),
        endDate: cfg.endDate || isoPlusYear(cfg.startDate || todayIso()),
        neverExpires: cfg.neverExpires !== undefined ? cfg.neverExpires : true,
        modules: (existing && existing.modules && existing.modules.length) ? existing.modules : MODULES.map(function (m) { return m.id; })
      };
      if (FREQUENCIES.indexOf(state.frequency) === -1) state.frequency = 'Weekly';

      var overlay = document.createElement('div');
      overlay.className = 'modal-overlay schedule-modal';
      overlay.innerHTML =
        '<div class="modal-dialog" role="dialog" aria-modal="true">' +
          '<div class="modal-dialog__title">' + (isEdit ? 'Edit schedule' : 'Schedule an Audit') + '</div>' +
          '<div class="modal-dialog__body">' +
            '<div class="form-field">' +
              '<label for="scheduleUrlInput">Website URL</label>' +
              '<input type="url" id="scheduleUrlInput" placeholder="https://example.com" value="' + U.escapeHtml(existing ? existing.url : '') + '"' + (isEdit ? ' disabled' : '') + '>' +
            '</div>' +

            '<div class="form-field">' +
              '<label>Frequency</label>' +
              '<div class="freq-toggle" role="group" aria-label="Frequency">' +
                FREQUENCIES.map(function (f) {
                  return '<button type="button" class="freq-toggle__btn' + (state.frequency === f ? ' is-active' : '') + '" data-freq="' + f + '" aria-pressed="' + (state.frequency === f) + '">' + f + '</button>';
                }).join('') +
              '</div>' +
            '</div>' +

            '<div data-frequency-fields></div>' +

            '<div class="form-field">' +
              '<label class="form-section-label">Audit Configuration</label>' +
              '<div class="form-field__hint" style="margin-top:-4px;">Audit Scope</div>' +
              '<div class="depth-select">' +
                '<label class="depth-option">' +
                  '<input type="radio" name="scheduleDepth" value="homepage"' + (!existing || existing.depth === 'homepage' ? ' checked' : '') + '>' +
                  '<div class="depth-option__title"><span class="depth-option__radio"></span>Homepage only</div>' +
                '</label>' +
                '<label class="depth-option">' +
                  '<input type="radio" name="scheduleDepth" value="full"' + (existing && existing.depth === 'full' ? ' checked' : '') + '>' +
                  '<div class="depth-option__title"><span class="depth-option__radio"></span>Full website</div>' +
                '</label>' +
              '</div>' +
              '<div class="form-field__hint" style="margin-top:var(--sp-3);">Modules</div>' +
              '<div class="module-select">' +
                MODULES.map(function (m) {
                  return '<label class="checkbox-field">' +
                    '<input type="checkbox" name="scheduleModule" value="' + m.id + '"' + (state.modules.indexOf(m.id) !== -1 ? ' checked' : '') + '>' +
                    m.label +
                  '</label>';
                }).join('') +
              '</div>' +
            '</div>' +

            '<div class="schedule-period">' +
              '<div class="schedule-period__title">Schedule Period</div>' +
              '<div class="schedule-period__hint">How long this recurring schedule stays active — not how often it repeats.</div>' +
              '<div class="form-grid">' +
                '<div class="form-field">' +
                  '<label for="schedulePeriodStart">Start Date</label>' +
                  '<input type="date" id="schedulePeriodStart" value="' + U.escapeHtml(state.startDate) + '">' +
                '</div>' +
                '<div class="form-field">' +
                  '<label for="schedulePeriodEnd">End Date</label>' +
                  '<input type="date" id="schedulePeriodEnd" value="' + U.escapeHtml(state.endDate) + '"' + (state.neverExpires ? ' disabled' : '') + '>' +
                '</div>' +
              '</div>' +
              '<label class="checkbox-field">' +
                '<input type="checkbox" id="schedulePeriodNeverExpires"' + (state.neverExpires ? ' checked' : '') + '>' +
                'Never expires' +
              '</label>' +
            '</div>' +
          '</div>' +
          '<div class="modal-dialog__actions">' +
            '<button type="button" class="btn btn--secondary" data-action="cancel">Cancel</button>' +
            '<button type="button" class="btn btn--primary" data-action="save">' + (isEdit ? 'Save changes' : 'Create Schedule') + '</button>' +
          '</div>' +
        '</div>';

      document.body.appendChild(overlay);
      document.body.style.overflow = 'hidden';

      var urlInput = overlay.querySelector('#scheduleUrlInput');
      var fieldsHost = overlay.querySelector('[data-frequency-fields]');
      var startInput = overlay.querySelector('#schedulePeriodStart');
      var endInput = overlay.querySelector('#schedulePeriodEnd');
      var neverExpiresInput = overlay.querySelector('#schedulePeriodNeverExpires');

      function renderFrequencyFields() {
        var html;
        if (state.frequency === 'Daily') {
          html =
            '<div class="form-grid">' +
              '<div class="form-field">' +
                '<label for="scheduleTimeInput">Time</label>' +
                '<input type="text" id="scheduleTimeInput" placeholder="09:00 AM" value="' + U.escapeHtml(state.time) + '">' +
              '</div>' +
              '<div class="form-field">' +
                '<label for="scheduleTimezoneInput">Timezone</label>' +
                '<select id="scheduleTimezoneInput">' + selectOptions(TIMEZONES, state.timezone) + '</select>' +
              '</div>' +
            '</div>' +
            '<div class="form-field__hint schedule-summary">Runs every day at ' + U.escapeHtml(state.time) + ' (' + U.escapeHtml(state.timezone) + ').</div>';
        } else if (state.frequency === 'Weekly') {
          html =
            '<div class="form-grid">' +
              '<div class="form-field">' +
                '<label for="scheduleWeekdayInput">Day</label>' +
                '<select id="scheduleWeekdayInput">' + selectOptions(WEEKDAYS, state.weekday) + '</select>' +
              '</div>' +
              '<div class="form-field">' +
                '<label for="scheduleTimeInput">Time</label>' +
                '<input type="text" id="scheduleTimeInput" placeholder="09:00 AM" value="' + U.escapeHtml(state.time) + '">' +
              '</div>' +
            '</div>' +
            '<div class="form-field">' +
              '<label for="scheduleTimezoneInput">Timezone</label>' +
              '<select id="scheduleTimezoneInput">' + selectOptions(TIMEZONES, state.timezone) + '</select>' +
            '</div>' +
            '<div class="form-field__hint schedule-summary">Runs every ' + U.escapeHtml(state.weekday) + ' at ' + U.escapeHtml(state.time) + ' (' + U.escapeHtml(state.timezone) + ').</div>';
        } else if (state.frequency === 'Monthly') {
          var monthDayOptions = [];
          for (var d = 1; d <= 31; d++) monthDayOptions.push(d);
          html =
            '<div class="form-field">' +
              '<label for="scheduleMonthDayInput">Day</label>' +
              '<select id="scheduleMonthDayInput"' + (state.monthDayMode === 'last' ? ' disabled' : '') + '>' + selectOptions(monthDayOptions, state.monthDay) + '</select>' +
            '</div>' +
            '<div class="radio-row">' +
              '<label class="radio-row__option">' +
                '<input type="radio" name="scheduleMonthDayMode" value="specific"' + (state.monthDayMode === 'specific' ? ' checked' : '') + '>' +
                'Specific day' +
              '</label>' +
              '<label class="radio-row__option">' +
                '<input type="radio" name="scheduleMonthDayMode" value="last"' + (state.monthDayMode === 'last' ? ' checked' : '') + '>' +
                'Last day of month' +
              '</label>' +
            '</div>' +
            '<div class="form-field">' +
              '<label for="scheduleTimeInput">Time</label>' +
              '<input type="text" id="scheduleTimeInput" placeholder="09:00 AM" value="' + U.escapeHtml(state.time) + '">' +
            '</div>' +
            '<div class="form-field__hint schedule-summary">Runs on ' + (state.monthDayMode === 'last' ? 'the last day of every month' : 'the ' + ordinal(state.monthDay) + ' of every month') + ' at ' + U.escapeHtml(state.time) + '.</div>';
        } else { // Yearly
          var yearDayOptions = [];
          for (var y = 1; y <= 31; y++) yearDayOptions.push(y);
          html =
            '<div class="form-grid">' +
              '<div class="form-field">' +
                '<label for="scheduleYearMonthInput">Month</label>' +
                '<select id="scheduleYearMonthInput">' + selectOptions(MONTHS, state.yearMonth) + '</select>' +
              '</div>' +
              '<div class="form-field">' +
                '<label for="scheduleYearDayInput">Day</label>' +
                '<select id="scheduleYearDayInput">' + selectOptions(yearDayOptions, state.yearDay) + '</select>' +
              '</div>' +
            '</div>' +
            '<div class="form-field">' +
              '<label for="scheduleTimeInput">Time</label>' +
              '<input type="text" id="scheduleTimeInput" placeholder="09:00 AM" value="' + U.escapeHtml(state.time) + '">' +
            '</div>' +
            '<div class="form-field__hint schedule-summary">Every year on ' + U.escapeHtml(state.yearMonth) + ' ' + U.escapeHtml(String(state.yearDay)) + ' at ' + U.escapeHtml(state.time) + '.</div>';
        }
        fieldsHost.innerHTML = html;
        bindFrequencyFieldEvents();
      }

      function bindFrequencyFieldEvents() {
        var timeEl = fieldsHost.querySelector('#scheduleTimeInput');
        if (timeEl) timeEl.addEventListener('input', function () { state.time = timeEl.value.trim(); updateSummary(); });

        var tzEl = fieldsHost.querySelector('#scheduleTimezoneInput');
        if (tzEl) tzEl.addEventListener('change', function () { state.timezone = tzEl.value; updateSummary(); });

        var weekdayEl = fieldsHost.querySelector('#scheduleWeekdayInput');
        if (weekdayEl) weekdayEl.addEventListener('change', function () { state.weekday = weekdayEl.value; updateSummary(); });

        var monthDayEl = fieldsHost.querySelector('#scheduleMonthDayInput');
        if (monthDayEl) monthDayEl.addEventListener('change', function () { state.monthDay = Number(monthDayEl.value); updateSummary(); });

        var monthDayModeEls = fieldsHost.querySelectorAll('input[name="scheduleMonthDayMode"]');
        monthDayModeEls.forEach(function (el) {
          el.addEventListener('change', function () {
            state.monthDayMode = el.value;
            if (monthDayEl) monthDayEl.disabled = state.monthDayMode === 'last';
            updateSummary();
          });
        });

        var yearMonthEl = fieldsHost.querySelector('#scheduleYearMonthInput');
        if (yearMonthEl) yearMonthEl.addEventListener('change', function () { state.yearMonth = yearMonthEl.value; updateSummary(); });

        var yearDayEl = fieldsHost.querySelector('#scheduleYearDayInput');
        if (yearDayEl) yearDayEl.addEventListener('change', function () { state.yearDay = Number(yearDayEl.value); updateSummary(); });
      }

      function updateSummary() {
        var summaryEl = fieldsHost.querySelector('.schedule-summary');
        if (!summaryEl) return;
        if (state.frequency === 'Daily') {
          summaryEl.textContent = 'Runs every day at ' + state.time + ' (' + state.timezone + ').';
        } else if (state.frequency === 'Weekly') {
          summaryEl.textContent = 'Runs every ' + state.weekday + ' at ' + state.time + ' (' + state.timezone + ').';
        } else if (state.frequency === 'Monthly') {
          summaryEl.textContent = 'Runs on ' + (state.monthDayMode === 'last' ? 'the last day of every month' : 'the ' + ordinal(state.monthDay) + ' of every month') + ' at ' + state.time + '.';
        } else {
          summaryEl.textContent = 'Every year on ' + state.yearMonth + ' ' + state.yearDay + ' at ' + state.time + '.';
        }
      }

      overlay.querySelectorAll('.freq-toggle__btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
          state.frequency = btn.getAttribute('data-freq');
          overlay.querySelectorAll('.freq-toggle__btn').forEach(function (b) {
            var active = b === btn;
            b.classList.toggle('is-active', active);
            b.setAttribute('aria-pressed', active);
          });
          renderFrequencyFields();
        });
      });

      renderFrequencyFields();

      neverExpiresInput.addEventListener('change', function () {
        state.neverExpires = neverExpiresInput.checked;
        endInput.disabled = state.neverExpires;
        if (endInput.disabled) endInput.classList.remove('is-invalid');
      });

      startInput.addEventListener('change', function () { state.startDate = startInput.value; });
      endInput.addEventListener('change', function () { state.endDate = endInput.value; });

      function close() {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        document.body.style.overflow = '';
      }

      overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
      overlay.querySelector('[data-action="cancel"]').addEventListener('click', close);

      overlay.querySelector('[data-action="save"]').addEventListener('click', function () {
        if (!isEdit) {
          if (!V.isValidUrl(urlInput.value)) {
            urlInput.classList.add('is-invalid');
            urlInput.focus();
            return;
          }
          urlInput.classList.remove('is-invalid');
        }

        if (!state.neverExpires && startInput.value && endInput.value && endInput.value < startInput.value) {
          endInput.classList.add('is-invalid');
          endInput.focus();
          return;
        }
        endInput.classList.remove('is-invalid');

        var depthInput = overlay.querySelector('input[name="scheduleDepth"]:checked');
        var moduleInputs = overlay.querySelectorAll('input[name="scheduleModule"]:checked');
        var modules = Array.prototype.map.call(moduleInputs, function (el) { return el.value; });

        var timeLabel = buildTimeLabel(state);

        var config = {
          url: urlInput.value.trim(),
          frequency: state.frequency,
          timeLabel: timeLabel,
          depth: depthInput ? depthInput.value : 'homepage',
          modules: modules,
          schedule: {
            time: state.time,
            timezone: state.timezone,
            weekday: state.weekday,
            monthDay: state.monthDay,
            monthDayMode: state.monthDayMode,
            yearMonth: state.yearMonth,
            yearDay: state.yearDay
          },
          schedulePeriod: {
            startDate: startInput.value,
            endDate: state.neverExpires ? null : endInput.value,
            neverExpires: state.neverExpires
          }
        };

        var request = isEdit
          ? window.Api.scheduler.update(existing.id, {
              frequency: config.frequency, timeLabel: config.timeLabel, depth: config.depth, modules: config.modules,
              schedule: config.schedule, schedulePeriod: config.schedulePeriod
            })
          : window.Api.scheduler.create(config);

        request.then(function () {
          window.Notifications.success(isEdit ? 'Schedule updated' : 'Schedule created', U.hostnameOf(config.url));
          close();
          load();
        }).catch(function (err) {
          window.Notifications.error('Couldn\'t save the schedule', err.message);
        });
      });
    }

    function buildTimeLabel(state) {
      if (state.frequency === 'Daily') return 'Daily, ' + state.time;
      if (state.frequency === 'Weekly') return state.weekday + 's, ' + state.time;
      if (state.frequency === 'Monthly') {
        return (state.monthDayMode === 'last' ? 'Last day of month' : ordinal(state.monthDay)) + ', ' + state.time;
      }
      return state.yearMonth + ' ' + state.yearDay + ', ' + state.time;
    }
  });
})();
