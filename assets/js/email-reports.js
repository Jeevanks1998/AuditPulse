/*
 * Email Reports page: every report emailed for this account, with counters,
 * a filterable table, and View / Resend (the dialog is email-composer.js).
 *
 * Status and website/subject search run on the server. Recipient search runs in
 * the browser on the current page (recipients are stored as JSON), and the count
 * label says so.
 */

(function () {
  var U = window.Utils;

  var PAGE_SIZE = 25;

  var ICONS = {
    file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7Z"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>'
  };

  document.addEventListener('DOMContentLoaded', function () {
    var tbody = document.getElementById('erHistoryBody');
    if (!tbody) return; // not on email-reports.html

    var esc = U.escapeHtml;

    var countEl = document.getElementById('erHistoryCount');
    var stateEl = document.getElementById('erHistoryState');
    var stateTextEl = document.getElementById('erHistoryStateText');
    var tableWrapEl = document.getElementById('erHistoryTable').parentNode;
    var pagerEl = document.getElementById('erPager');
    var pagerLabelEl = document.getElementById('erPagerLabel');
    var tabsEl = document.querySelector('.er-tabs');
    var searchInput = document.getElementById('emailReportsSearchInput');
    var composeBtn = document.getElementById('erComposeBtn');

    if (!window.Api || !U) {
      if (stateTextEl) stateTextEl.textContent = 'Configuration error: the page scripts didn\u2019t load.';
      return;
    }

    var state = {
      page: 1,
      total: 0,
      status: '',
      query: '',
      rows: [],             // current server page, before recipient filtering
      attachmentLabels: {}, // key -> label from the backend
      reportCache: {}       // auditId -> report, so reopening is instant
    };

    /* Attachment labels from the backend; if that fails, show the raw keys. */
    window.Api.reports.getAttachmentChoices()
      .then(function (map) {
        state.attachmentLabels = map || {};
        if (state.rows.length) renderRows();
      })
      .catch(function () { /* keys show as they are */ });

    function attachmentLabel(key) {
      return state.attachmentLabels[key] || key;
    }

    /* Stats */

    function renderStats(stats) {
      stats = stats || {};
      [
        ['statTotalSent', stats.totalSent],
        ['statSuccessful', stats.successful],
        ['statFailed', stats.failed],
        ['statReportsShared', stats.reportsShared]
      ].forEach(function (pair) {
        var el = document.getElementById(pair[0]);
        if (el) el.textContent = pair[1] == null ? '0' : pair[1];
      });
    }

    /* Rows */

    function matchesRow(entry, needle) {
      var host = (entry.auditUrl || '').toLowerCase();
      var subject = (entry.subject || '').toLowerCase();
      if (host.indexOf(needle) !== -1 || subject.indexOf(needle) !== -1) return true;

      // Recipient search (includes BCC: it's the sender's own record).
      var pool = (entry.recipientTo || [])
        .concat(entry.recipientCc || [])
        .concat(entry.recipientBcc || []);
      return pool.some(function (addr) {
        return String(addr).toLowerCase().indexOf(needle) !== -1;
      });
    }

    function visibleRows() {
      if (!state.query) return state.rows;
      var needle = state.query.toLowerCase();
      return state.rows.filter(function (entry) { return matchesRow(entry, needle); });
    }

    function recipientCellHtml(entry) {
      var to = entry.recipientTo || [];
      if (!to.length) return '<span class="text-tertiary">No recipients</span>';

      // One address plus a count; the full list is in View.
      var rest = (to.length - 1) +
        (entry.recipientCc || []).length +
        (entry.recipientBcc || []).length;

      return '<span class="er-cell__primary">' + esc(to[0]) + '</span>' +
        (rest > 0 ? '<span class="er-cell__more">+' + rest + ' more</span>' : '');
    }

    function attachmentsCellHtml(entry) {
      var keys = entry.attachments || [];
      if (!keys.length) return '<span class="text-tertiary">None</span>';

      var shown = keys.slice(0, 2).map(function (k) {
        return '<span class="er-file">' + ICONS.file +
          '<span>' + esc(attachmentLabel(k)) + '</span></span>';
      }).join('');
      var rest = keys.length - 2;

      return '<span class="er-files">' + shown +
        (rest > 0 ? '<span class="er-cell__more">+' + rest + '</span>' : '') +
      '</span>';
    }

    function rowHtml(entry) {
      var sent = entry.status === 'sent';
      var host = entry.auditUrl ? U.hostnameOf(entry.auditUrl) : ('Audit #' + entry.auditId);
      var when = entry.sentAt ? new Date(entry.sentAt) : null;

      return '<tr data-email-id="' + esc(entry.id) + '">' +
        '<td>' +
          '<div class="er-site">' +
            '<span class="er-site__favicon" aria-hidden="true">' +
              esc(U.faviconLetter(entry.auditUrl || '')) +
            '</span>' +
            '<span class="er-cell__primary">' + esc(host) + '</span>' +
          '</div>' +
        '</td>' +
        '<td>' + recipientCellHtml(entry) + '</td>' +
        '<td><span class="er-cell__subject">' + esc(entry.subject || '(no subject)') + '</span></td>' +
        '<td>' + attachmentsCellHtml(entry) + '</td>' +
        '<td>' +
          '<span class="er-cell__primary">' + (when ? esc(when.toLocaleDateString()) : '\u2014') + '</span>' +
          '<span class="er-cell__more">' +
            (entry.sentAt ? esc(U.formatRelativeTime(entry.sentAt)) : '') +
          '</span>' +
        '</td>' +
        '<td>' +
          '<span class="badge ' + (sent ? 'badge--success' : 'badge--error') + '">' +
            (sent ? 'Sent' : 'Failed') +
          '</span>' +
        '</td>' +
        '<td>' +
          '<div class="er-actions">' +
            '<button type="button" class="btn btn--ghost btn--sm" data-act="view">View</button>' +
            '<button type="button" class="btn btn--secondary btn--sm" data-act="resend">Resend</button>' +
          '</div>' +
        '</td>' +
      '</tr>';
    }

    function setPlaceholder(message) {
      if (message) {
        // 'block', not '': the CSS hides .er-state by default.
        stateEl.style.display = 'block';
        stateTextEl.textContent = message;
        tableWrapEl.style.display = 'none';
      } else {
        stateEl.style.display = 'none';
        tableWrapEl.style.display = '';
      }
    }

    function renderRows() {
      var rows = visibleRows();

      if (countEl) {
        if (!state.total) {
          countEl.textContent = 'No emails';
        } else if (state.query) {
          // "on this page": recipient search only sees fetched rows.
          countEl.textContent = rows.length + ' of ' + state.rows.length + ' on this page';
        } else {
          countEl.textContent = state.total + ' email' + (state.total === 1 ? '' : 's');
        }
      }

      if (!rows.length) {
        tbody.innerHTML = '';
        setPlaceholder(
          state.query ? 'No email matches that search.'
            : state.status ? 'No ' + state.status + ' emails yet.'
            : 'No reports have been emailed yet. Use \u201cSend a Report\u201d to send your first one.'
        );
      } else {
        setPlaceholder(null);
        tbody.innerHTML = rows.map(rowHtml).join('');
      }

      renderPager();
    }

    function renderPager() {
      var pages = Math.ceil(state.total / PAGE_SIZE) || 1;
      if (pages <= 1) { pagerEl.hidden = true; return; }

      pagerEl.hidden = false;
      pagerLabelEl.textContent = 'Page ' + state.page + ' of ' + pages;
      pagerEl.querySelector('[data-page="prev"]').disabled = state.page <= 1;
      pagerEl.querySelector('[data-page="next"]').disabled = state.page >= pages;
    }

    /* Loading */

    function load() {
      setPlaceholder('Loading email history\u2026');

      return window.Api.reports.listEmailHistory({
        // Search text goes to the server (website/subject across all pages).
        q: state.query || undefined,
        status: state.status || undefined,
        page: state.page,
        pageSize: PAGE_SIZE
      }).then(function (page) {
        state.rows = (page && page.items) || [];
        state.total = (page && page.total) || 0;
        renderStats(page && page.stats);
        renderRows();
      }).catch(function (err) {
        state.rows = [];
        state.total = 0;
        tbody.innerHTML = '';
        pagerEl.hidden = true;
        setPlaceholder((err && err.message) || 'Couldn\u2019t load your email history right now.');
      });
    }

    function reload() {
      // A new send appears on page 1.
      state.page = 1;
      return load();
    }

    /* Shared shell for the two read-only dialogs (detail and audit picker). */

    function openOverlay(innerHtml, opts) {
      opts = opts || {};
      var overlay = document.createElement('div');
      overlay.className = 'composer-overlay';
      overlay.innerHTML = innerHtml;
      document.body.appendChild(overlay);
      document.body.style.overflow = 'hidden';

      function close() {
        document.removeEventListener('keydown', onKey);
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        document.body.style.overflow = '';
        if (opts.trigger && opts.trigger.focus) opts.trigger.focus();
      }
      function onKey(e) { if (e.key === 'Escape') close(); }
      document.addEventListener('keydown', onKey);

      U.on(overlay, 'click', function (e) {
        if (e.target === overlay) { close(); return; }
        if (e.target.closest && e.target.closest('[data-act="close"]')) { close(); return; }
        if (opts.onClick) opts.onClick(e, close);
      });

      if (opts.focusSelector) {
        var target = overlay.querySelector(opts.focusSelector);
        if (target) target.focus();
      }
      return { el: overlay, close: close };
    }

    function dialogHeadHtml(title, sub, faviconSeed) {
      return '<div class="composer__head">' +
        '<div class="composer__site">' +
          (faviconSeed !== null
            ? '<div class="composer__favicon" aria-hidden="true">' +
                esc(U.faviconLetter(faviconSeed || '')) + '</div>'
            : '') +
          '<div style="min-width:0;">' +
            '<h2 class="composer__title">' + esc(title) + '</h2>' +
            '<div class="composer__sub">' + esc(sub) + '</div>' +
          '</div>' +
        '</div>' +
        '<button type="button" class="icon-btn composer__close" data-act="close" aria-label="Close">' +
          ICONS.close +
        '</button>' +
      '</div>';
    }

    /* View */

    function detailBodyHtml(entry) {
      var sent = entry.status === 'sent';
      var host = entry.auditUrl ? U.hostnameOf(entry.auditUrl) : ('Audit #' + entry.auditId);
      var keys = entry.attachments || [];

      function line(label, value) {
        return value ? '<dt>' + esc(label) + '</dt><dd>' + esc(value) + '</dd>' : '';
      }

      return '<div class="er-detail">' +
        '<div class="er-detail__head">' +
          '<h3 class="er-detail__subject">' + esc(entry.subject || '(no subject)') + '</h3>' +
          '<span class="badge ' + (sent ? 'badge--success' : 'badge--error') + '">' +
            (sent ? 'Sent' : 'Failed') +
          '</span>' +
        '</div>' +
        (!sent && entry.errorMessage
          ? '<p class="er-detail__error">' + esc(entry.errorMessage) + '</p>'
          : '') +
        '<dl class="er-detail__meta">' +
          line('Website', host) +
          line('Report', '#' + entry.auditId) +
          line('To', (entry.recipientTo || []).join(', ')) +
          line('Cc', (entry.recipientCc || []).join(', ')) +
          line('Bcc', (entry.recipientBcc || []).join(', ')) +
          line('Date', entry.sentAt ? new Date(entry.sentAt).toLocaleString() : '') +
        '</dl>' +
        (entry.body
          ? '<pre class="er-detail__body">' + esc(entry.body) + '</pre>'
          // Older rows have no saved body.
          : '<p class="email-empty">The message body wasn\u2019t recorded for this send.</p>') +
        (keys.length
          ? '<div class="er-detail__files">' +
              '<div class="er-detail__files-label">Attachments</div>' +
              '<div class="er-detail__files-list">' +
                keys.map(function (k) {
                  return '<span class="er-file">' + ICONS.file +
                    '<span>' + esc(attachmentLabel(k)) + '</span></span>';
                }).join('') +
              '</div>' +
            '</div>'
          : '') +
      '</div>';
    }

    function openDetail(entry, trigger) {
      var host = entry.auditUrl ? U.hostnameOf(entry.auditUrl) : ('Audit #' + entry.auditId);

      var dialog = openOverlay(
        '<div class="composer er-detail-dialog" role="dialog" aria-modal="true">' +
          dialogHeadHtml('Sent email', host, entry.auditUrl || '') +
          '<div class="composer__body">' + detailBodyHtml(entry) + '</div>' +
          '<div class="composer__foot">' +
            '<div class="composer__foot-main">' +
              '<button type="button" class="btn btn--secondary" data-act="close">Close</button>' +
              '<button type="button" class="btn btn--primary" data-act="resend">' +
                ICONS.send + 'Resend' +
              '</button>' +
            '</div>' +
          '</div>' +
        '</div>',
        {
          trigger: trigger,
          focusSelector: '.composer__foot [data-act="close"]',
          onClick: function (e, close) {
            var btn = e.target.closest ? e.target.closest('[data-act="resend"]') : null;
            if (!btn) return;
            // Pass the record straight to the composer.
            close();
            openComposer(entry.auditId, entry, trigger);
          }
        }
      );

      return dialog;
    }

    /* The composer needs the report first; Resend also passes the previous send as `prefill`. */

    function openComposer(auditId, prefill, trigger) {
      if (!window.EmailComposer) {
        window.Notifications.error('Composer unavailable',
          'Please reload the page and try again.');
        return;
      }

      function show(report) {
        window.EmailComposer.open({
          auditId: auditId,
          report: report,
          prefill: prefill || null,
          trigger: trigger,
          onSent: reload
        });
      }

      if (state.reportCache[auditId]) { show(state.reportCache[auditId]); return; }

      if (trigger) trigger.disabled = true;
      window.Api.reports.get(auditId).then(function (report) {
        state.reportCache[auditId] = report;
        show(report);
      }).catch(function (err) {
        // Usually the audit was deleted after it was emailed.
        window.Notifications.error('Couldn\u2019t open that report',
          (err && err.message) || 'The audit may no longer exist.');
      }).finally(function () {
        if (trigger) trigger.disabled = false;
      });
    }

    /* Row actions */

    U.on(tbody, 'click', function (e) {
      var btn = e.target.closest ? e.target.closest('[data-act]') : null;
      if (!btn || btn.disabled) return;

      var row = btn.closest('tr');
      var emailId = Number(row && row.getAttribute('data-email-id'));
      if (!emailId) return;

      var act = btn.getAttribute('data-act');
      btn.disabled = true;

      // Refetch the full record (the row doesn't have the body or BCC).
      window.Api.reports.getEmailRecord(emailId).then(function (entry) {
        if (act === 'view') openDetail(entry, btn);
        else openComposer(entry.auditId, entry, btn);
      }).catch(function (err) {
        window.Notifications.error('Couldn\u2019t open that email',
          (err && err.message) || 'Please try again.');
      }).finally(function () {
        btn.disabled = false;
      });
    });

    /* "Send a Report": pick a completed audit first */

    function auditPickerHtml(audits) {
      return '<div class="composer er-picker-dialog" role="dialog" aria-modal="true">' +
        dialogHeadHtml('Choose a report', 'Completed audits, newest first', null) +
        '<div class="composer__body">' +
          '<div class="er-list">' +
            audits.map(function (audit) {
              var score = audit.overallScore;
              var band = score == null ? null : U.scoreBand(score);
              var when = audit.completedAt || audit.createdAt;
              return '<button type="button" class="er-item" data-audit-id="' + esc(audit.id) + '">' +
                '<span class="er-item__favicon" aria-hidden="true">' +
                  esc(U.faviconLetter(audit.url)) + '</span>' +
                '<span class="er-item__main">' +
                  '<span class="er-item__host">' + esc(U.hostnameOf(audit.url)) + '</span>' +
                  '<span class="er-item__meta">' +
                    (when ? 'Completed ' + esc(U.formatRelativeTime(when)) : 'Completed') +
                  '</span>' +
                '</span>' +
                (band ? '<span class="score-chip score-chip--' + band + '">' + esc(score) + '</span>' : '') +
                '<span class="er-item__send">' + ICONS.send + '<span>Send to POC</span></span>' +
              '</button>';
            }).join('') +
          '</div>' +
        '</div>' +
      '</div>';
    }

    U.on(composeBtn, 'click', function () {
      composeBtn.disabled = true;

      window.Api.history.list({ status: 'completed', pageSize: 50 })
        .then(function (page) {
          var audits = (page && page.items) || [];
          if (!audits.length) {
            window.Notifications.info('No completed audits',
              'Run an audit first — finished reports can then be emailed from here.');
            return;
          }

          openOverlay(auditPickerHtml(audits), {
            trigger: composeBtn,
            focusSelector: '.er-item',
            onClick: function (e, close) {
              var item = e.target.closest ? e.target.closest('.er-item') : null;
              if (!item) return;
              var auditId = Number(item.getAttribute('data-audit-id'));
              if (!auditId) return;

              // Close first: two stacked dialogs would both trap focus.
              close();
              openComposer(auditId, null, composeBtn);
            }
          });
        })
        .catch(function (err) {
          window.Notifications.error('Couldn\u2019t load your reports',
            (err && err.message) || 'Please try again.');
        })
        .finally(function () { composeBtn.disabled = false; });
    });

    /* Filters */

    U.on(tabsEl, 'click', function (e) {
      var tab = e.target.closest ? e.target.closest('.er-tab') : null;
      if (!tab) return;

      var next = tab.getAttribute('data-status') || '';
      if (next === state.status) return;

      state.status = next;
      state.page = 1;

      U.qsa('.er-tab', tabsEl).forEach(function (t) {
        var active = t === tab;
        t.classList.toggle('is-active', active);
        t.setAttribute('aria-selected', active ? 'true' : 'false');
      });

      load();
    });

    // Debounced so responses don't arrive out of order.
    var searchTimer = null;
    U.on(searchInput, 'input', function () {
      state.query = (searchInput.value || '').trim();

      // Filter what's on screen now, then ask the server once typing stops.
      renderRows();

      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        state.page = 1;
        load();
      }, 300);
    });

    U.on(pagerEl, 'click', function (e) {
      var btn = e.target.closest ? e.target.closest('[data-page]') : null;
      if (!btn || btn.disabled) return;

      var pages = Math.ceil(state.total / PAGE_SIZE) || 1;
      var next = btn.getAttribute('data-page') === 'next' ? state.page + 1 : state.page - 1;
      if (next < 1 || next > pages) return;

      state.page = next;
      load();
    });

    /* Start */

    load();
  });
})();
