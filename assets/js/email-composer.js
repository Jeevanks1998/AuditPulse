/* ==========================================================================
   email-composer.js — the "Send to POC" dialog. Exposed as
   window.EmailComposer.

   WHY THIS FILE EXISTS
   --------------------
   The composer used to be duplicated: once inside assets/js/app.js (now
   renamed assets/js/report.js — see that file's header) at the top level
   of report.html's page controller, and once more in an assets/js/report.js
   on disk that had gotten corrupted into holding HTML instead of JS.
   email-reports.html loaded the corrupted file, not app.js, so its
   "Send to POC" button had no working composer at all. This file is now
   the single source of truth: both report.html and email-reports.html
   load it directly, so a fix here can't be duplicated out of sync again.

   Styling is NOT defined here. assets/css/report.css already carries the
   full composer stylesheet (.composer-overlay, .mailhead/.mailrow,
   .recipients/.chip, .opt-group/.opt, .preview/.file-chip, plus the
   <=640px full-screen-sheet treatment), so this module renders against
   those exact class names. Both pages must link report.css.

   PUBLIC API
   ----------
   EmailComposer.open({
     auditId,           // required — the audit whose report is being sent
     report,            // required — a ReportOut (url, overall, generatedAt, ...)
     prefill,           // optional — an EmailHistoryOut to reload ("Resend")
     trigger,           // optional — element focus returns to on close
     onSent             // optional — callback(result) after a successful send
   })

   `prefill` is what makes Resend work: pass a previous send and every
   field (to/cc/bcc, subject, body, attachment checkboxes) comes back
   exactly as it went out, instead of regenerating defaults.
   ========================================================================== */

window.EmailComposer = (function () {
  var U = window.Utils;
  var V = window.Validation;

  /* The default message. Mirrors backend/emailer/templates.py's _TEMPLATE
     — same six {{tokens}}, same wording — so the text the user sees here
     is the text the backend would have generated had `body` been omitted.
     Keep the two in sync. */
  var EMAIL_BODY_TEMPLATE = [
    'Hi {{poc_name}},',
    '',
    'Please find attached the latest AuditPulse website audit report for {{website_name}}.',
    '',
    'Audit Date: {{audit_date}}',
    'Report ID: {{report_id}}',
    'Overall Score: {{overall_score}}/100',
    'Overall Status: {{overall_status}}',
    '',
    'The detailed report and supporting evidence are attached for your review.',
    '',
    'Please let us know if any clarification is required.',
    '',
    'Regards,',
    'AuditPulse'
  ].join('\n');

  var ICONS = {
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>',
    remove: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>',
    alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>',
    file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7Z"/></svg>'
  };

  /* Fallback labels, used only if GET /reports/email/attachment-choices
     fails. Not the source of truth — the backend owns that list
     (emailer/attachments.py ATTACHMENT_CHOICES), and a hardcoded list here
     would silently drift from what the server can actually attach. */
  var FALLBACK_CHOICES = { pdf: 'Audit Report PDF' };

  var openInstance = null; // only ever one composer at a time

  /* -------------------------------- helpers -------------------------------- */

  function esc(s) { return U.escapeHtml(s); }

  function fillEmailTemplate(template, values) {
    return template.replace(/{{\s*([a-zA-Z0-9_]+)\s*}}/g, function (whole, token) {
      var val = values[token];
      return (val === undefined || val === null || val === '') ? whole : String(val);
    });
  }

  function scoreStatusLabel(score) {
    if (score == null) return '—';
    var band = U.scoreBand(score);
    return band === 'good' ? 'Healthy' : band === 'mid' ? 'Needs Attention' : 'Critical';
  }

  /* "19 Sep 2026" — day, short month name, year. Mirrors
     backend/emailer/templates.py's build_subject() formatting so a
     backend-generated subject (body omitted from the send request) reads
     identically to the one this page shows and lets the user edit. */
  function formatSubjectDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return d.getDate() + ' ' + months[d.getMonth()] + ' ' + d.getFullYear();
  }

  function defaultSubject(report) {
    var host = U.hostnameOf(report.url || '') || (report.url || '');
    var when = formatSubjectDate(report.generatedAt);
    return 'AuditPulse | Website Audit Report – ' + host + (when ? ' | ' + when : '');
  }

  function defaultBody(report, auditId) {
    return fillEmailTemplate(EMAIL_BODY_TEMPLATE, {
      poc_name: 'there',
      website_name: report.url || '',
      audit_date: (report.generatedAt || '').slice(0, 10) || '—',
      report_id: auditId,
      overall_score: report.overall == null ? '—' : report.overall,
      overall_status: scoreStatusLabel(report.overall)
    });
  }

  /* Splits pasted/typed recipient text. Accepts comma, semicolon, and
     whitespace separators, because people paste address lists out of
     Outlook and Sheets in all three forms and silently losing half of a
     pasted list is far worse than accepting a separator we didn't plan for. */
  function splitAddresses(text) {
    return String(text || '')
      .split(/[,;\s]+/)
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
  }

  function isValidEmail(addr) {
    return V && V.isValidEmail ? V.isValidEmail(addr) : /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(addr);
  }

  /* ------------------------------ recipient field ------------------------------
     A chip list backed by a plain array. Each entry keeps its own validity so
     an address that fails the format check still renders (as .chip--invalid)
     rather than vanishing — a chip that disappears on blur reads as "accepted"
     and the user finds out at send time. */

  function RecipientField(rowEl, opts) {
    var self = this;
    this.addresses = [];
    this.rowEl = rowEl;
    this.wrapEl = rowEl.querySelector('.recipients');
    this.inputEl = rowEl.querySelector('.recipients__input');
    this.errorEl = rowEl.querySelector('.field__error');
    this.required = !!(opts && opts.required);
    this.onChange = (opts && opts.onChange) || function () {};

    U.on(this.inputEl, 'keydown', function (e) {
      if (e.key === 'Enter' || e.key === ',' || e.key === ';' || e.key === 'Tab') {
        if (self.inputEl.value.trim()) {
          // Tab still moves focus on — it just commits what's typed first,
          // so tabbing out of a half-entered address doesn't discard it.
          if (e.key !== 'Tab') e.preventDefault();
          self.commit();
        }
      } else if (e.key === 'Backspace' && !self.inputEl.value && self.addresses.length) {
        // Backspace on an empty input edits the last chip rather than
        // deleting it outright, so a typo is fixable without retyping.
        var last = self.addresses.pop();
        self.inputEl.value = last.value;
        self.render();
      }
    });

    U.on(this.inputEl, 'blur', function () { self.commit(); });
    U.on(this.inputEl, 'paste', function (e) {
      var text = (e.clipboardData || window.clipboardData).getData('text');
      if (text && /[,;\s]/.test(text)) {
        e.preventDefault();
        self.add(text);
      }
    });

    // Clicking anywhere in the chip area focuses the input — the whole
    // block should behave like one text field.
    U.on(this.wrapEl, 'click', function (e) {
      if (e.target === self.wrapEl) self.inputEl.focus();
    });

    U.on(this.wrapEl, 'click', function (e) {
      var btn = e.target.closest ? e.target.closest('.chip__remove') : null;
      if (!btn) return;
      var idx = Number(btn.getAttribute('data-idx'));
      self.addresses.splice(idx, 1);
      self.render();
      self.onChange();
    });
  }

  RecipientField.prototype.add = function (text) {
    var self = this;
    splitAddresses(text).forEach(function (addr) {
      var exists = self.addresses.some(function (a) {
        return a.value.toLowerCase() === addr.toLowerCase();
      });
      if (exists) return; // duplicates are silently dropped, not double-sent
      self.addresses.push({ value: addr, valid: isValidEmail(addr) });
    });
    this.render();
    this.onChange();
  };

  RecipientField.prototype.commit = function () {
    var text = this.inputEl.value;
    if (!text.trim()) return;
    this.inputEl.value = '';
    this.add(text);
  };

  RecipientField.prototype.setValues = function (addresses) {
    this.addresses = (addresses || []).map(function (addr) {
      return { value: addr, valid: isValidEmail(addr) };
    });
    this.render();
  };

  RecipientField.prototype.values = function () {
    return this.addresses.map(function (a) { return a.value; });
  };

  RecipientField.prototype.invalidValues = function () {
    return this.addresses.filter(function (a) { return !a.valid; })
      .map(function (a) { return a.value; });
  };

  RecipientField.prototype.render = function () {
    var chips = this.addresses.map(function (a, i) {
      return '<span class="chip' + (a.valid ? '' : ' chip--invalid') + '">' +
        '<span class="chip__text">' + esc(a.value) + '</span>' +
        '<button type="button" class="chip__remove" data-idx="' + i + '" ' +
          'aria-label="Remove ' + esc(a.value) + '">' + ICONS.remove + '</button>' +
      '</span>';
    }).join('');

    // The <input> is re-inserted rather than replaced so focus and any
    // in-progress text survive a re-render.
    var input = this.inputEl;
    var value = input.value;
    var hadFocus = document.activeElement === input;
    this.wrapEl.innerHTML = chips;
    this.wrapEl.appendChild(input);
    input.value = value;
    if (hadFocus) input.focus();
  };

  RecipientField.prototype.setError = function (message) {
    if (this.errorEl) {
      this.errorEl.textContent = message || '';
      this.errorEl.style.display = message ? '' : 'none';
    }
    this.rowEl.classList.toggle('is-invalid', !!message);
  };

  /* --------------------------------- markup --------------------------------- */

  function recipientRowHtml(id, label, required) {
    return '<div class="mailrow" data-row="' + id + '">' +
      '<label class="mailrow__label" for="' + id + 'Input">' + esc(label) +
        (required ? '<span class="mailrow__req" aria-hidden="true">*</span>' : '') +
      '</label>' +
      '<div class="mailrow__control">' +
        '<p class="field__error" style="display:none;"></p>' +
        '<div class="recipients">' +
          '<input class="recipients__input" id="' + id + 'Input" type="email" multiple ' +
            'autocomplete="off" placeholder="name@company.com">' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function optionHtml(key, label) {
    return '<label class="opt" data-opt="' + esc(key) + '">' +
      '<input type="checkbox" class="opt__box" value="' + esc(key) + '">' +
      '<span class="opt__text"><span class="opt__name">' + esc(label) + '</span></span>' +
    '</label>';
  }

  function composerHtml(report, auditId) {
    var host = U.hostnameOf(report.url || '');
    return '<div class="composer" role="dialog" aria-modal="true" aria-labelledby="composerTitle">' +
      '<div class="composer__head">' +
        '<div class="composer__site">' +
          '<div class="composer__favicon" aria-hidden="true">' + esc(U.faviconLetter(report.url)) + '</div>' +
          '<div style="min-width:0;">' +
            '<h2 class="composer__title" id="composerTitle">Send report to POC</h2>' +
            '<div class="composer__sub">' + esc(host) + ' · Report #' + esc(auditId) + '</div>' +
          '</div>' +
        '</div>' +
        '<button type="button" class="icon-btn composer__close" data-act="close" aria-label="Close">' +
          ICONS.close +
        '</button>' +
      '</div>' +

      '<div class="composer__alert" role="alert" hidden>' + ICONS.alert +
        '<span data-alert-text></span>' +
      '</div>' +

      '<div class="composer__body">' +
        '<div class="composer__view" data-view="edit">' +
          '<div class="mailhead">' +
            recipientRowHtml('composerTo', 'To', true) +
            recipientRowHtml('composerCc', 'Cc', false) +
            recipientRowHtml('composerBcc', 'Bcc', false) +
            '<div class="mailrow" data-row="subject">' +
              '<label class="mailrow__label" for="composerSubject">Subject</label>' +
              '<div class="mailrow__control">' +
                '<p class="field__error" style="display:none;"></p>' +
                '<input class="mailrow__input" id="composerSubject" type="text" ' +
                  'maxlength="255" autocomplete="off">' +
              '</div>' +
            '</div>' +
          '</div>' +

          '<div class="composer__section">' +
            '<div class="composer__section-head">' +
              '<label class="composer__label" for="composerBody">Message</label>' +
              '<button type="button" class="btn btn--ghost btn--sm" data-act="reset-body">' +
                'Reset to default' +
              '</button>' +
            '</div>' +
            '<textarea class="composer__textarea" id="composerBody"></textarea>' +
            '<p class="field__error" style="display:none;" data-err="body"></p>' +
          '</div>' +

          '<fieldset class="opt-group" data-attachments>' +
            '<legend class="opt-group__legend">Attachments</legend>' +
            '<p class="composer__hint">Anything with no data for this audit is skipped rather ' +
              'than sent empty — the send confirmation lists what actually went out.</p>' +
            '<div class="opt-list" data-opt-list>' +
              '<p class="email-empty">Loading options…</p>' +
            '</div>' +
          '</fieldset>' +
        '</div>' +

        '<div class="composer__view" data-view="preview" hidden></div>' +
      '</div>' +

      '<div class="composer__foot">' +
        '<button type="button" class="btn btn--secondary" data-act="toggle-preview">Preview</button>' +
        '<div class="composer__foot-main">' +
          '<button type="button" class="btn btn--secondary" data-act="close">Cancel</button>' +
          '<button type="button" class="btn btn--primary" data-act="send">' +
            ICONS.send + '<span data-send-label>Send email</span>' +
          '</button>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  /* ---------------------------------- open ---------------------------------- */

  function open(opts) {
    opts = opts || {};
    if (!opts.report || !opts.auditId) {
      window.Notifications.error('Couldn\u2019t open the composer', 'The report is still loading.');
      return null;
    }
    if (openInstance) openInstance.close();

    var report = opts.report;
    var auditId = opts.auditId;
    var prefill = opts.prefill || null;
    var trigger = opts.trigger || document.activeElement;

    var overlay = document.createElement('div');
    overlay.className = 'composer-overlay';
    overlay.innerHTML = composerHtml(report, auditId);
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';

    var dialog = overlay.querySelector('.composer');
    var alertEl = overlay.querySelector('.composer__alert');
    var alertTextEl = overlay.querySelector('[data-alert-text]');
    var subjectEl = overlay.querySelector('#composerSubject');
    var bodyEl = overlay.querySelector('#composerBody');
    var bodyErrEl = overlay.querySelector('[data-err="body"]');
    var optListEl = overlay.querySelector('[data-opt-list]');
    var editView = overlay.querySelector('[data-view="edit"]');
    var previewView = overlay.querySelector('[data-view="preview"]');
    var previewBtn = overlay.querySelector('[data-act="toggle-preview"]');
    var sendBtn = overlay.querySelector('[data-act="send"]');
    var sendLabel = overlay.querySelector('[data-send-label]');

    var sending = false;
    var previewing = false;
    var choices = {};

    function clearAlert() { alertEl.hidden = true; alertTextEl.textContent = ''; }
    function showAlert(msg) { alertTextEl.textContent = msg; alertEl.hidden = false; }

    var toField = new RecipientField(overlay.querySelector('[data-row="composerTo"]'), {
      required: true,
      onChange: function () { toField.setError(''); clearAlert(); }
    });
    var ccField = new RecipientField(overlay.querySelector('[data-row="composerCc"]'), {
      onChange: function () { ccField.setError(''); }
    });
    var bccField = new RecipientField(overlay.querySelector('[data-row="composerBcc"]'), {
      onChange: function () { bccField.setError(''); }
    });

    /* ---- prefill: a resend reloads the previous send verbatim ---- */
    subjectEl.value = (prefill && prefill.subject) || defaultSubject(report);
    // An old history row (written before `body` was stored) comes back
    // empty. Falling back to the default template is right: that is the
    // text the backend would have generated for it at the time.
    bodyEl.value = (prefill && prefill.body) || defaultBody(report, auditId);
    if (prefill) {
      toField.setValues(prefill.recipientTo || []);
      ccField.setValues(prefill.recipientCc || []);
      bccField.setValues(prefill.recipientBcc || []);
    }

    /* ---- attachment checkboxes ---- */
    function renderChoices(map) {
      choices = map;
      var keys = Object.keys(map);
      if (!keys.length) {
        optListEl.innerHTML = '<p class="email-empty">No attachment options available.</p>';
        return;
      }
      optListEl.innerHTML = keys.map(function (k) { return optionHtml(k, map[k]); }).join('');

      // A resend restores exactly the keys recorded on that send; a fresh
      // compose starts at the PDF only — never everything, which would
      // quietly mail a full evidence package to a client.
      var checked = (prefill && prefill.attachments && prefill.attachments.length)
        ? prefill.attachments
        : ['pdf'];

      U.qsa('.opt__box', optListEl).forEach(function (box) {
        box.checked = checked.indexOf(box.value) !== -1;
        box.closest('.opt').classList.toggle('is-checked', box.checked);
      });
    }

    U.on(optListEl, 'change', function (e) {
      var box = e.target.closest ? e.target.closest('.opt__box') : null;
      if (!box) return;
      box.closest('.opt').classList.toggle('is-checked', box.checked);
      clearAlert();
    });

    window.Api.reports.getAttachmentChoices()
      .then(renderChoices)
      .catch(function () { renderChoices(FALLBACK_CHOICES); });

    function selectedAttachments() {
      return U.qsa('.opt__box', optListEl)
        .filter(function (b) { return b.checked; })
        .map(function (b) { return b.value; });
    }

    /* ---------------------------- preview ---------------------------- */

    function renderPreview() {
      var files = selectedAttachments();
      var cc = ccField.values();
      var bcc = bccField.values();

      previewView.innerHTML = '<div class="preview">' +
        '<div class="preview__head">' +
          '<h3 class="preview__subject">' + esc(subjectEl.value || '(no subject)') + '</h3>' +
          '<dl class="preview__meta">' +
            '<dt>To</dt><dd>' + esc(toField.values().join(', ') || '—') + '</dd>' +
            (cc.length ? '<dt>Cc</dt><dd>' + esc(cc.join(', ')) + '</dd>' : '') +
            (bcc.length ? '<dt>Bcc</dt><dd>' + esc(bcc.join(', ')) + '</dd>' : '') +
          '</dl>' +
        '</div>' +
        '<pre class="preview__text">' + esc(bodyEl.value) + '</pre>' +
        (files.length
          ? '<div class="preview__files">' +
              '<div class="preview__files-label">Attachments</div>' +
              '<div class="preview__files-list">' +
                files.map(function (k) {
                  return '<span class="file-chip">' + ICONS.file +
                    '<span>' + esc(choices[k] || k) + '</span></span>';
                }).join('') +
              '</div>' +
            '</div>'
          : '') +
      '</div>';
    }

    function setPreview(on) {
      previewing = on;
      if (on) renderPreview();
      editView.hidden = on;
      previewView.hidden = !on;
      previewBtn.textContent = on ? 'Back to edit' : 'Preview';
    }

    /* ----------------------------- validation ----------------------------- */

    function validate() {
      // Commit anything half-typed first, or a user who fills in an address
      // and clicks Send without leaving the field gets "recipient required".
      toField.commit(); ccField.commit(); bccField.commit();

      var ok = true;
      clearAlert();
      toField.setError(''); ccField.setError(''); bccField.setError('');

      if (!toField.values().length) {
        toField.setError('At least one recipient is required.');
        ok = false;
      }

      [[toField, 'To'], [ccField, 'Cc'], [bccField, 'Bcc']].forEach(function (pair) {
        var bad = pair[0].invalidValues();
        if (bad.length) {
          pair[0].setError('Not a valid email address: ' + bad.join(', '));
          ok = false;
        }
      });

      if (!bodyEl.value.trim()) {
        bodyErrEl.textContent = 'The message can\u2019t be empty.';
        bodyErrEl.style.display = '';
        bodyEl.classList.add('is-invalid');
        ok = false;
      } else {
        bodyErrEl.style.display = 'none';
        bodyEl.classList.remove('is-invalid');
      }

      if (!selectedAttachments().length) {
        showAlert('Pick at least one attachment to send.');
        ok = false;
      }

      if (!ok && previewing) setPreview(false); // errors live on the edit view
      return ok;
    }

    /* -------------------------------- send -------------------------------- */

    function send() {
      if (sending || !validate()) return;

      sending = true;
      sendBtn.disabled = true;
      sendLabel.textContent = 'Sending…';

      window.Api.reports.sendToPoc(auditId, {
        to: toField.values(),
        cc: ccField.values(),
        bcc: bccField.values(),
        subject: subjectEl.value.trim(),
        body: bodyEl.value,
        attachments: selectedAttachments()
      }).then(function (result) {
        // The endpoint returns 200 for a *recorded* attempt, including a
        // failed one (that's the point of Email History) — so success is
        // read off the payload, never off the HTTP status.
        if (result && result.success) {
          window.Notifications.success('Report sent',
            'Emailed to ' + toField.values().join(', ') + '.');
          close();
          if (opts.onSent) opts.onSent(result);
        } else {
          showAlert((result && result.errorMessage) ||
            'The email couldn\u2019t be sent. The attempt was recorded in Email History.');
          if (opts.onSent) opts.onSent(result); // refresh the table: the failure is a new row
        }
      }).catch(function (err) {
        showAlert((err && err.message) || 'The email couldn\u2019t be sent. Please try again.');
      }).finally(function () {
        sending = false;
        sendBtn.disabled = false;
        sendLabel.textContent = 'Send email';
      });
    }

    /* ------------------------------- wiring ------------------------------- */

    U.on(overlay, 'click', function (e) {
      // Clicking the backdrop closes — but not mid-send, which would hide
      // the outcome of a request that's still going.
      if (e.target === overlay && !sending) { close(); return; }

      var btn = e.target.closest ? e.target.closest('[data-act]') : null;
      if (!btn) return;
      var act = btn.getAttribute('data-act');

      if (act === 'close' && !sending) close();
      else if (act === 'send') send();
      else if (act === 'toggle-preview') setPreview(!previewing);
      else if (act === 'reset-body') {
        bodyEl.value = defaultBody(report, auditId);
        subjectEl.value = defaultSubject(report);
        bodyEl.classList.remove('is-invalid');
        bodyErrEl.style.display = 'none';
      }
    });

    U.on(bodyEl, 'input', function () {
      bodyEl.classList.remove('is-invalid');
      bodyErrEl.style.display = 'none';
    });

    function onKeydown(e) {
      if (e.key === 'Escape' && !sending) { close(); return; }

      // Focus trap. Without it, tabbing past the last control lands on the
      // page behind the overlay, which is still scrollable and clickable.
      if (e.key !== 'Tab') return;
      var focusable = U.qsa(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        dialog
      ).filter(function (el) { return el.offsetParent !== null; });
      if (!focusable.length) return;

      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    }
    document.addEventListener('keydown', onKeydown);

    function close() {
      document.removeEventListener('keydown', onKeydown);
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      document.body.style.overflow = '';
      openInstance = null;
      if (trigger && trigger.focus) trigger.focus();
    }

    // Resending already has its recipients; a fresh compose does not, so
    // each opens on the field that actually needs attention.
    if (prefill && toField.values().length) bodyEl.focus();
    else overlay.querySelector('#composerToInput').focus();

    openInstance = { close: close };
    return openInstance;
  }

  return {
    open: open,
    // Exported so email-reports.js can render the same default text when it
    // has no stored body to fall back on.
    defaultSubject: defaultSubject,
    defaultBody: defaultBody
  };
})();
