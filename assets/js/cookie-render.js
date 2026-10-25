/*
 * Cookie Scanner tab on the report page (data from GET /audits/{id}/cookies):
 * tiles, filters, the cookie table with row details, browser storage and CSV
 * export. Exposes window.CookieRender.
 */
(function () {
  'use strict';

  var U = window.Utils;
  var esc = function (s) { return U.escapeHtml(s == null ? '' : String(s)); };

  var CATS = [
    ['marketing', 'Marketing / advertising'],
    ['analytics', 'Analytics'],
    ['functional', 'Functional'],
    ['consent_management', 'Consent management'],
    ['essential', 'Strictly necessary'],
    ['unknown', 'Unknown']
  ];
  var WHEN = [
    ['before_consent', 'B', 'Before consent'],
    ['after_reject', 'R', 'After Reject'],
    ['after_accept', 'A', 'After Accept'],
    ['journey', 'J', 'While browsing']
  ];

  function yn(v) { return v === true ? 'Yes' : (v === false ? 'No' : '—'); }

  function tile(label, value, sub, state) {
    return '<div class="ck-tile" data-state="' + (state || 'neutral') + '">' +
      '<span class="ck-tile__value">' + esc(value) + '</span>' +
      '<span class="ck-tile__label">' + esc(label) + '</span>' +
      (sub ? '<span class="ck-tile__sub">' + esc(sub) + '</span>' : '') + '</div>';
  }

  function seenCell(c, tested) {
    return '<span class="ck-seen">' + WHEN.map(function (w) {
      var v = c.seen ? c.seen[w[0]] : null;
      var st = tested.indexOf(w[0]) === -1 || v == null ? 'na' : (v ? 'yes' : 'no');
      var bad = st === 'yes' && c.requires_consent && (w[0] === 'before_consent' || w[0] === 'after_reject');
      var title = w[2] + ': ' + (st === 'na' ? 'not tested' : (st === 'yes' ? 'present' : 'not present'));
      return '<span class="ck-dot ck-dot--' + st + (bad ? ' ck-dot--bad' : '') + '" title="' + esc(title) + '">' + w[1] + '</span>';
    }).join('') + '</span>';
  }

  function flagCell(c) {
    if (c.detail_missing) return '<span class="ck-muted">Not recorded</span>';
    function f(name, v, badWhenFalse) {
      var cls = v === true ? 'on' : (v === false ? (badWhenFalse ? 'bad' : 'off') : 'na');
      return '<span class="ck-flag ck-flag--' + cls + '" title="' + name + ': ' + yn(v) + '">' + name + '</span>';
    }
    return f('Secure', c.secure, c.party === 'third' || c.same_site === 'None') +
      f('HttpOnly', c.http_only, false) +
      '<span class="ck-flag ck-flag--' + (c.same_site ? 'on' : 'na') + '" title="SameSite">' + esc(c.same_site || 'SameSite —') + '</span>';
  }

  function statusChip(c) {
    if (c.status === 'issue') return '<span class="ck-chip ck-chip--issue">' + c.issues.length + (c.issues.length === 1 ? ' issue' : ' issues') + '</span>';
    if (c.status === 'review') return '<span class="ck-chip ck-chip--review">Review</span>';
    return '<span class="ck-chip ck-chip--ok">OK</span>';
  }

  function detailRow(c, labels) {
    var pages = (c.pages || []).map(function (p) {
      return '<li><a href="' + esc(p) + '" target="_blank" rel="noopener noreferrer">' + esc(p) + '</a></li>';
    }).join('');
    var more = c.page_count > (c.pages || []).length ? '<li class="ck-muted">+ ' + (c.page_count - c.pages.length) + ' more</li>' : '';
    var rows = [
      ['Purpose', c.purpose || '—'],
      ['Vendor', c.vendor || '—'],
      ['Path', c.path || '/'],
      ['Expires', c.session ? 'When the browser closes' : (c.expires_at || c.lifetime_label)],
      ['Size', c.size ? c.size + ' bytes' : '—'],
      ['First seen', c.first_seen || '—'],
      ['Needs consent', c.requires_consent ? 'Yes (analytics / marketing)' : 'No']
    ].map(function (r) { return '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>'; }).join('');
    var issues = (c.issues || []).length
      ? '<ul class="ck-issues">' + c.issues.map(function (i) { return '<li>' + esc(i) + '</li>'; }).join('') + '</ul>'
      : (c.status === 'review'
        ? '<p class="ck-muted">AuditPulse does not recognise this cookie. Check with the site team what it does and whether it needs consent.</p>'
        : '<p class="ck-muted">No problems found for this cookie.</p>');
    return '<div class="ck-detail"><div><p class="ck-detail__h">What we found</p>' + issues +
      '<dl class="ck-dl">' + rows + '</dl></div>' +
      '<div><p class="ck-detail__h">Pages where it appeared</p>' +
      (pages ? '<ul class="ck-pages">' + pages + more + '</ul>' : '<p class="ck-muted">—</p>') + '</div></div>';
  }

  function render(inv, ids, opts) {
    opts = opts || {};
    var content = document.getElementById(ids.content);
    var empty = document.getElementById(ids.empty);
    var chip = document.getElementById(ids.chip);
    if (!content) return null;

    if (!inv || !inv.available) {
      content.style.display = 'none';
      if (empty) {
        empty.style.display = '';
        empty.textContent = 'No cookie data was recorded for this audit. Cookies are captured by the Consent check ' +
          '(before consent, after Reject, after Accept) and by the Journey Map on every page it visits. ' +
          'Audits run before the Cookie Scanner was added, or where the website blocked the audit browser, have none. ' +
          'Run a new audit with Consent (and Journey Map for all pages) to see the full cookie list.';
      }
      if (chip) chip.textContent = 'Not scanned';
      return inv || null;
    }
    if (empty) empty.style.display = 'none';
    content.style.display = '';

    var s = inv.summary || {};
    var tested = inv.states_tested || [];
    var cookies = inv.cookies || [];
    if (chip) chip.textContent = s.total + (s.total === 1 ? ' cookie' : ' cookies');

    var state = { q: '', cat: '', party: '', when: '', status: '', open: {} };

    var catCounts = s.by_category || {};
    var tiles =
      tile('Cookies found', s.total, s.first_party + ' first-party · ' + s.third_party + ' third-party', 'neutral') +
      tile('Tracking before consent', tested.indexOf('before_consent') === -1 ? '—' : s.before_consent_required,
        tested.indexOf('before_consent') === -1 ? 'Not tested' : 'Analytics / marketing set before the visitor chose',
        tested.indexOf('before_consent') === -1 ? 'neutral' : (s.before_consent_required ? 'fail' : 'pass')) +
      tile('Tracking after Reject', tested.indexOf('after_reject') === -1 ? '—' : s.after_reject_required,
        tested.indexOf('after_reject') === -1 ? 'Not tested' : 'Still present after Reject',
        tested.indexOf('after_reject') === -1 ? 'neutral' : (s.after_reject_required ? 'fail' : 'pass')) +
      tile('Cookies with issues', s.with_issues, 'Consent, lifetime or security', s.with_issues ? 'fail' : 'pass') +
      tile('Unknown', catCounts.unknown || 0, 'Not recognised — review', (catCounts.unknown || 0) ? 'warn' : 'pass') +
      tile('Pages scanned', s.pages_scanned, s.pages_scanned > 1 ? 'Homepage + Journey Map pages' : 'Homepage only', 'neutral');

    var bars = CATS.filter(function (c) { return catCounts[c[0]]; }).map(function (c) {
      var n = catCounts[c[0]] || 0;
      var pct = s.total ? Math.round((n / s.total) * 100) : 0;
      return '<button type="button" class="ck-bar" data-cat="' + c[0] + '" title="Show only ' + esc(c[1]) + '">' +
        '<span class="ck-bar__label">' + esc(c[1]) + '</span>' +
        '<span class="ck-bar__track"><span class="ck-bar__fill ck-cat--' + c[0] + '" style="width:' + pct + '%"></span></span>' +
        '<span class="ck-bar__n">' + n + '</span></button>';
    }).join('');

    var notes = (inv.notes || []).map(function (n) { return '<p class="ck-note">' + esc(n) + '</p>'; }).join('');

    var catOpts = '<option value="">All categories</option>' + CATS.filter(function (c) { return catCounts[c[0]]; })
      .map(function (c) { return '<option value="' + c[0] + '">' + esc(c[1]) + ' (' + catCounts[c[0]] + ')</option>'; }).join('');
    var whenOpts = '<option value="">Any time</option>' + WHEN.filter(function (w) { return tested.indexOf(w[0]) !== -1; })
      .map(function (w) { return '<option value="' + w[0] + '">Present ' + esc(w[2].toLowerCase()) + '</option>'; }).join('');

    var storage = inv.storage || [];
    var labels = inv.state_labels || {};
    var storageHtml = storage.length
      ? '<details class="ck-storage"><summary>Browser storage on the homepage (' + storage.length + ' keys)</summary>' +
        '<div class="ck-tablewrap"><table class="ck-table ck-table--small"><thead><tr><th>Key</th><th>Type</th><th>Seen</th></tr></thead><tbody>' +
        storage.map(function (x) {
          return '<tr><td class="ck-mono">' + esc(x.key) + '</td><td>' + esc(x.type) + '</td><td>' +
            esc((x.states || []).map(function (st) { return labels[st] || st; }).join(', ')) + '</td></tr>';
        }).join('') + '</tbody></table></div></details>'
      : '';

    content.innerHTML =
      '<p class="ck-headline">' + esc(inv.headline || '') + '</p>' +
      '<div class="ck-tiles">' + tiles + '</div>' + notes +
      (bars ? '<div class="ck-block"><p class="ck-title">By category</p><div class="ck-bars">' + bars + '</div></div>' : '') +
      '<div class="ck-block">' +
        '<div class="ck-toolbar">' +
          '<input type="search" class="ck-input" id="ckSearch" placeholder="Search name, domain, vendor…" aria-label="Search cookies">' +
          '<select class="ck-input" id="ckCat" aria-label="Category">' + catOpts + '</select>' +
          '<select class="ck-input" id="ckParty" aria-label="Party"><option value="">First & third party</option><option value="first">First-party</option><option value="third">Third-party</option></select>' +
          '<select class="ck-input" id="ckWhen" aria-label="When present">' + whenOpts + '</select>' +
          '<select class="ck-input" id="ckStatus" aria-label="Status"><option value="">Any status</option><option value="issue">Issues only</option><option value="review">Needs review</option><option value="ok">OK</option></select>' +
          '<button type="button" class="btn btn--secondary ck-export" id="ckExport">Export CSV</button>' +
        '</div>' +
        '<p class="ck-legend">Seen: <b>B</b> before consent · <b>R</b> after Reject · <b>A</b> after Accept · <b>J</b> while browsing other pages. Red = a tracking cookie where it should not be. Grey = not tested.</p>' +
        '<p class="ck-count" id="ckCount"></p>' +
        '<div class="ck-tablewrap"><table class="ck-table"><thead><tr>' +
          '<th>Cookie</th><th>Category</th><th>Party</th><th>Lifetime</th><th>Settings</th><th>Seen</th><th>Status</th>' +
        '</tr></thead><tbody id="ckBody"></tbody></table></div>' +
      '</div>' + storageHtml;

    function matches(c) {
      if (state.cat && c.category !== state.cat) return false;
      if (state.party && c.party !== state.party) return false;
      if (state.when && !(c.seen && c.seen[state.when])) return false;
      if (state.status && c.status !== state.status) return false;
      if (state.q) {
        var hay = [c.name, c.domain, c.vendor, c.purpose, c.category_label, c.set_by_page].join(' ').toLowerCase();
        if (hay.indexOf(state.q) === -1) return false;
      }
      return true;
    }

    function draw() {
      var list = cookies.filter(matches);
      var body = document.getElementById('ckBody');
      var count = document.getElementById('ckCount');
      if (count) count.textContent = 'Showing ' + list.length + ' of ' + cookies.length + ' cookies';
      if (!list.length) {
        body.innerHTML = '<tr><td colspan="7" class="ck-muted ck-emptyrow">No cookies match these filters.</td></tr>';
        return;
      }
      body.innerHTML = list.map(function (c, i) {
        var key = c.name + '|' + c.domain + '|' + c.path;
        var open = !!state.open[key];
        return '<tr class="ck-row' + (open ? ' is-open' : '') + '" data-key="' + esc(key) + '" tabindex="0" aria-expanded="' + open + '">' +
          '<td data-label="Cookie"><span class="ck-name ck-mono">' + esc(c.name) + '</span><span class="ck-domain">' + esc(c.domain) + '</span></td>' +
          '<td data-label="Category"><span class="ck-cat ck-cat--' + esc(c.category) + '">' + esc(c.category_label) + '</span>' +
            (c.vendor ? '<span class="ck-domain">' + esc(c.vendor) + '</span>' : '') + '</td>' +
          '<td data-label="Party">' + (c.party === 'third' ? 'Third' : 'First') + '</td>' +
          '<td data-label="Lifetime" class="' + (c.exceeds_retention ? 'ck-warn' : '') + '">' + esc(c.lifetime_label) + '</td>' +
          '<td data-label="Settings" class="ck-flags">' + flagCell(c) + '</td>' +
          '<td data-label="Seen">' + seenCell(c, tested) + '</td>' +
          '<td data-label="Status">' + statusChip(c) + '</td></tr>' +
          (open ? '<tr class="ck-detailrow"><td colspan="7">' + detailRow(c, labels) + '</td></tr>' : '');
      }).join('');
      U.qsa('.ck-row', body).forEach(function (row) {
        function toggle() { state.open[row.dataset.key] = !state.open[row.dataset.key]; draw(); }
        U.on(row, 'click', toggle);
        U.on(row, 'keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
      });
    }

    function bind(id, key, lower) {
      var el = document.getElementById(id);
      if (!el) return;
      U.on(el, 'input', function () { state[key] = lower ? el.value.trim().toLowerCase() : el.value; draw(); });
      U.on(el, 'change', function () { state[key] = lower ? el.value.trim().toLowerCase() : el.value; draw(); });
    }
    bind('ckSearch', 'q', true);
    bind('ckCat', 'cat');
    bind('ckParty', 'party');
    bind('ckWhen', 'when');
    bind('ckStatus', 'status');

    U.qsa('.ck-bar', content).forEach(function (b) {
      U.on(b, 'click', function () {
        var sel = document.getElementById('ckCat');
        state.cat = state.cat === b.dataset.cat ? '' : b.dataset.cat;
        if (sel) sel.value = state.cat;
        draw();
      });
    });

    var exportBtn = document.getElementById('ckExport');
    if (exportBtn && opts.onExport) U.on(exportBtn, 'click', function () { opts.onExport(exportBtn); });

    draw();
    return inv;
  }

  window.CookieRender = { render: render };
})();
