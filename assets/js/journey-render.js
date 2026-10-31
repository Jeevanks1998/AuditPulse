/* Journey Map UI (report section and dashboard card), rendered from report_view as is. Exposes window.JourneyRender. */

(function () {
  var U = window.Utils;
  var esc = function (v) { return U.escapeHtml(v == null ? '' : String(v)); };

  // Tracking result per interaction (what was seen). Plain "Tracked" is never used.
  var ANALYTICS_CHIP = {
    analytics_hit: ['tracked', 'Analytics Hit Detected'],
    datalayer: ['datalayer', 'DataLayer Event Detected'],
    both: ['tracked', 'Both Detected'],
    not_detected: ['not_tracked', 'Not Detected'],
    duplicate: ['duplicate', 'Duplicate Detected'],
    unable: ['not_tested', 'Unable to Validate'],
    safety_restricted: ['skipped', 'Not Tested — Safety Restricted'],
    not_applicable: ['not_applicable', '—']
  };
  // Older scans: only "not detected" and "duplicate" can be stated.
  var LEGACY_TRACK = { not_tracked: 'not_detected', duplicate: 'duplicate', not_applicable: 'not_applicable' };
  var TEST_CHIP = {
    success: ['success', 'Worked'], failed: ['failed', 'Failed'],
    skipped: ['skipped', 'Not Tested — Safety Restricted'], not_tested: ['', 'Not tested'],
    same_as_first: ['', 'Same as first occurrence'],
    consent_control: ['', 'Consent control']
  };
  var IMPORTANCE_CHIP = { high: ['failed', 'High importance'], medium: ['skipped', 'Medium importance'], low: ['', 'Low importance'] };
  var JOURNEY_STATUS = { broken: 'failed', tracking_gap: 'not_tracked', not_verified: 'not_tested', ok: 'success' };

  function origin() { return (window.APP_CONFIG && window.APP_CONFIG.API_ORIGIN) || ''; }
  function img(url) { return url ? origin() + url : null; }
  function chip(cls, text) { return '<span class="jr-chip' + (cls ? ' jr-chip--' + cls : '') + '">' + esc(text) + '</span>'; }
  function analyticsKey(r) { return (r && r.analytics_result) || LEGACY_TRACK[r && r.tracking_status] || 'unable'; }
  function analyticsChip(r) { var c = ANALYTICS_CHIP[analyticsKey(r)] || ANALYTICS_CHIP.unable; return chip(c[0], c[1]); }
  function importanceChip(level) { var c = IMPORTANCE_CHIP[level]; return c ? chip(c[0], c[1]) : ''; }
  function trackChip(st) { return analyticsChip({ tracking_status: st }); }
  function testChip(st) { var c = TEST_CHIP[st] || ['', st || '']; return chip(c[0], c[1]); }
  function band(score) { return score == null ? 'mid' : (score >= 80 ? 'good' : score >= 50 ? 'mid' : 'bad'); }

  function table(headers, rows, rowAttrs) {
    if (!rows.length) return '<p class="jr-muted">Nothing discovered.</p>';
    return '<div class="jr-table-wrap"><table class="jr-table"><thead><tr>' +
      headers.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      rows.map(function (r, i) { return '<tr' + (rowAttrs ? rowAttrs(i) : '') + '>' + r.map(function (c) { return '<td>' + c + '</td>'; }).join('') + '</tr>'; }).join('') +
      '</tbody></table></div>';
  }

  /* Health */
  function renderHealth(view) {
    var ex = view.health_explained || {};
    var pct = function (v) { return v == null ? '—' : Math.round(v * 100) + '%'; };
    var parts = (ex.parts || []).map(function (p) {
      return '<div class="jr-part"><div class="jr-part__head"><strong>' + esc(p.label) + '</strong>' +
        '<span>' + pct(p.rate) + ' × ' + p.weight + ' = <strong>' + (p.points == null ? '—' : p.points) + '</strong> pts</span></div>' +
        '<span class="jr-bar__track"><span class="jr-bar__fill" style="width:' + Math.round((p.rate || 0) * 100) + '%"></span></span>' +
        '<small class="jr-muted">' + esc(p.detail) + '</small></div>';
    }).join('');
    var crit = ex.critical_failures || 0;
    var summary = (ex.parts || []).map(function (p) { return '<li>' + esc(p.label) + ': <strong>' + pct(p.rate) + '</strong></li>'; }).join('');
    return '<div class="jr-health">' +
      '<div class="jr-score" data-band="' + band(view.score) + '">' +
        '<span class="jr-score__label">Journey Health</span>' +
        '<span class="jr-score__value">' + (view.score == null ? '—' : view.score) + '<small>/100</small></span>' +
        (summary ? '<ul class="jr-score__parts">' + summary + '</ul>' : '') + '</div>' +
      '<div>' +
        (parts ? '<p class="jr-muted" style="margin:0 0 6px;">Calculated from this audit\'s results: ' + esc(ex.formula || '') + '.</p>' +
          '<div class="jr-parts">' + parts + '</div>'
          : '<p class="jr-muted">No interaction could be executed in this scan, so no health score was calculated.</p>') +
        '<p class="jr-muted" style="margin-top:8px;">Critical failures found: <strong style="color:' + (crit ? 'var(--color-error)' : 'inherit') + '">' + crit + '</strong>' +
          (crit ? ' — ' + esc((ex.critical_titles || []).join(' · ')) : '') + '</p>' +
        '<div class="jr-tiles">' + (view.tiles || []).map(function (t) {
          return '<div class="jr-tile"' + (t.state ? ' data-state="' + esc(t.state) + '"' : '') + '>' +
            '<span class="jr-tile__value">' + esc(t.value) + '</span><span class="jr-tile__label">' + esc(t.label) + '</span></div>';
        }).join('') + '</div>' +
        (view.consent_state ? '<p class="jr-muted" style="margin-top:6px;">Consent state during the scan: <strong>' + esc(view.consent_state) + '</strong></p>' : '') +
      '</div></div>';
  }

  function renderSummary(view) {
    var items = view.by_type || [];
    if (!items.length) return '<p class="jr-muted">No interactive elements were discovered in this scan.</p>';
    var max = items.reduce(function (m, b) { return Math.max(m, b.count); }, 1);
    return '<div class="jr-bars">' + items.map(function (b) {
      return '<div class="jr-bar"><span>' + esc(b.type) + '</span><span class="jr-bar__track"><span class="jr-bar__fill" style="width:' +
        Math.round((b.count / max) * 100) + '%"></span></span><span class="jr-bar__n">' + b.count + '</span></div>';
    }).join('') + '</div>' +
    '<p class="jr-muted">' + esc((view.counts || {}).interactions_total_including_repeats || 0) + ' elements found in total across ' +
      esc((view.counts || {}).pages_scanned || 0) + ' page(s); repeats of the same element (e.g. the main navigation on every page) are counted once. ' +
      esc((view.counts || {}).dynamic_elements || 0) + ' of them rendered by JavaScript after load (not in the server HTML).</p>';
  }

  /* Map */
  function stepButton(node, nid) {
    if (!node) return '';
    if (node.kind === 'page') {
      return '<button type="button" class="jr-step jr-step--page" data-node="' + esc(nid) + '">' +
        '<span class="jr-step__kind">Page</span><span class="jr-step__label">' + esc(node.path) + '</span></button>';
    }
    var a = analyticsKey(node);
    var trk = { both: 'tracked', analytics_hit: 'tracked', datalayer: 'datalayer', duplicate: 'duplicate',
      not_detected: 'not_tracked', unable: 'not_tested', safety_restricted: 'not_tested', not_applicable: 'not_tested' }[a] || 'not_tested';
    if (trk === 'not_tracked' && node.test_status !== 'success') trk = 'not_tested';   // failed steps aren't tracking gaps
    return '<button type="button" class="jr-step jr-step--interaction" data-node="' + esc(nid) + '" data-tracking="' + esc(trk) + '"' +
      (node.test_status === 'failed' ? ' data-failed="true"' : '') + ' title="' + esc((ANALYTICS_CHIP[a] || ANALYTICS_CHIP.unable)[1]) + '">' +
      '<span class="jr-step__kind">' + esc(node.type_label) + '</span><span class="jr-step__label">' + esc(node.label) + '</span></button>';
  }

  function journeyFlow(j, nodes, compact) {
    var meta = compact ? '' :
      '<span class="jr-flow__meta">' + (j.goal_type_label ? chip('type', j.goal_type_label) : '') + importanceChip(j.importance) +
        (j.status === 'tracking_gap' && (j.tracking_gaps || []).length
          ? chip('not_tracked', j.tracking_gaps.length + ' tracking gap' + (j.tracking_gaps.length === 1 ? '' : 's'))
          : chip(JOURNEY_STATUS[j.status] || '', j.status_label || '')) +
      '</span>';
    return '<div class="jr-flow" data-status="' + esc(j.status || '') + '"><span class="jr-flow__name">' + esc(j.name) + '</span>' + meta +
      '<div class="jr-flow__steps">' + (j.steps || []).map(function (sid, i) {
        return (i ? '<span class="jr-arrow" aria-hidden="true">→</span>' : '') + stepButton(nodes[sid], sid);
      }).join('') + '</div></div>';
  }

  function renderMap(view) {
    var map = view.map || {};
    var nodes = map.nodes || {};
    var journeys = map.journeys || [];
    var flows = journeys.map(function (j) { return journeyFlow(j, nodes, false); }).join('');
    return '<div class="jr-legend"><span class="l-tracked">Tracked</span><span class="l-gap">Not tracked</span>' +
      '<span>Not tested</span><span class="l-gap">Dashed border = did not work</span></div>' +
      '<p class="jr-title" style="margin-top:4px;">' + journeys.length + ' journey path' + (journeys.length === 1 ? '' : 's') + ' found' +
      (journeys.length ? ' <span class="jr-muted" style="font-weight:400;">— most critical first</span>' : '') + '</p>' +
      '<div class="jr-flows">' + (flows || '<p class="jr-muted">No journey path was found — no important action (CTA, form, download, sign-up, booking, purchase, phone or email link) was found on the scanned pages.</p>') + '</div>';
  }

  function shotLinks(shots) {
    return ['highlighted', 'before', 'after', 'form'].filter(function (k) { return shots[k]; }).map(function (k) {
      return '<a class="jr-shot" href="' + esc(img(shots[k])) + '" target="_blank" rel="noopener"><img src="' + esc(img(shots[k])) + '" alt="' + esc(k) + ' screenshot" loading="lazy">' +
        esc({ highlighted: 'Highlighted (detected element)', before: 'Before interaction', after: 'After interaction', form: 'Form' }[k]) + '</a>';
    }).join('');
  }

  function renderDetail(view, nid) {
    var map = view.map || {};
    var n = (map.nodes || {})[nid];
    if (!n) return '<p class="jr-muted">Select a page or interaction in a journey path to see its evidence.</p>';
    if (n.kind === 'page') {
      return '<h4>' + esc(n.title || n.path) + '</h4><dl>' +
        '<dt>Page</dt><dd>' + esc(n.url) + '</dd>' +
        '<dt>Status</dt><dd>' + esc(n.status || '—') + (n.error ? ' · ' + esc(n.error) : '') + '</dd>' +
        '<dt>Found via</dt><dd>' + esc(n.via_label || (n.parent ? '—' : 'Start page')) + '</dd>' +
        '<dt>Elements</dt><dd>' + esc(n.interaction_count) + '</dd></dl>' +
        (n.screenshot ? '<div class="jr-shots"><a class="jr-shot" href="' + esc(img(n.screenshot)) + '" target="_blank" rel="noopener"><img src="' + esc(img(n.screenshot)) + '" alt="Page screenshot" loading="lazy">Full page</a></div>' : '');
    }
    var row = (view.interactions || []).filter(function (r) { return r.index === n.index; })[0] || {};
    var shotHtml = shotLinks(row.screenshots || {});
    return '<h4>' + esc(row.label || n.label) + '</h4>' +
      (shotHtml ? '<div class="jr-shots jr-shots--top">' + shotHtml + '</div>' : '<p class="jr-muted">No screenshot was captured for this interaction.</p>') +
      '<dl>' +
      '<dt>Type</dt><dd>' + chip('type', row.type_label || n.type_label) + importanceChip(row.importance) + '</dd>' +
      '<dt>Page</dt><dd>' + esc(row.page_path || n.path) + '</dd>' +
      (row.destination ? '<dt>Destination</dt><dd>' + esc(row.destination) + '</dd>' : '') +
      '<dt>Test result</dt><dd>' + testChip(row.test_status || n.test_status) + '</dd>' +
      '<dt>Safety</dt><dd>' + esc(row.safety_label || '—') + (row.safety_reason ? '<br><small>' + esc(row.safety_reason) + '</small>' : '') + '</dd>' +
      '<dt>Observed</dt><dd>' + esc(row.observed || n.observed || '—') + '</dd>' +
      (row.final_url && row.final_url !== row.page ? '<dt>Ended on</dt><dd>' + esc(row.final_url) + '</dd>' : '') +
      ((row.steps || []).length ? '<dt>How it was tested</dt><dd><ol class="jr-steps-list">' +
        row.steps.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ol></dd>' : '') +
      '<dt>Analytics</dt><dd>' + analyticsChip(row) +
        ((row.tracking_events || []).length ? '<br>' + esc(row.tracking_events.join(', ')) : '') +
        (row.analytics_reason ? '<br><small>' + esc(row.analytics_reason) + '</small>' :
          (row.tracking_note ? '<br><small>' + esc(row.tracking_note) + '</small>' : '')) + '</dd>' +
      '<dt>Signals</dt><dd>' + esc((row.signals || []).join(' · ') || '—') + '</dd>' +
      ((n.issues || []).length ? '<dt>Issues</dt><dd>' + n.issues.map(function (i) { var f = (view.findings || [])[i]; return f ? esc(f.title) : ''; }).join('<br>') + '</dd>' : '') +
      '</dl>';
  }

  function nodeIdForIndex(view, index) { return 'int:' + index; }

  function wireMap(root, detailEl, view) {
    root.addEventListener('click', function (e) {
      var b = e.target.closest('[data-node]');
      if (!b) return;
      root.querySelectorAll('.jr-step.is-selected').forEach(function (x) { x.classList.remove('is-selected'); });
      root.querySelectorAll('[data-node="' + b.getAttribute('data-node') + '"]').forEach(function (x) { x.classList.add('is-selected'); });
      detailEl.innerHTML = renderDetail(view, b.getAttribute('data-node'));
    });
  }

  /* Interaction details */
  var INTERACTION_FILTERS = [
    ['tested', 'All tested'], ['gap', 'Not tracked'], ['failed', "Didn't work"], ['forms', 'Forms'],
    ['downloads', 'Downloads'], ['cta', 'Main buttons'], ['not_tested', 'Not tested'], ['all', 'Everything found']
  ];
  var MAX_INTERACTION_ROWS = 200;
  var FORM_TYPES = { form: 1, form_start: 1, form_submit: 1 };

  function isTested(r) { return r.test_status === 'success' || r.test_status === 'failed'; }

  function filterInteractions(rows, f) {
    return rows.filter(function (r) {
      if (f === 'tested') return isTested(r);
      if (f === 'gap') return r.test_status === 'success' && analyticsKey(r) === 'not_detected';
      if (f === 'failed') return r.test_status === 'failed';
      if (f === 'forms') return !!FORM_TYPES[r.type];
      if (f === 'downloads') return r.type === 'download';
      if (f === 'cta') return r.type === 'cta' || r.type === 'signup' || r.type === 'appointment' || r.type === 'purchase';
      if (f === 'not_tested') return !isTested(r);
      return true;
    });
  }

  function shortDest(r) {
    var d = r.destination || '';
    try {
      var u = new URL(d, r.page || undefined), p = new URL(r.page);
      if (u.host === p.host && /^https?:$/.test(u.protocol)) return (u.pathname || '/') + u.search;
    } catch (e) { /* not a URL (tel:, mailto:, javascript:) */ }
    return d;
  }

  var SAFETY_SHORT = { executed: 'Executed', checked: 'HTTP check only', not_executed: 'Safety restricted',
    consent: 'Consent control', repeat: 'Repeat element', not_selected: 'Not selected for test' };
  function safetyCell(r) {
    return '<span title="' + esc(r.safety_label || '') + '">' + esc(SAFETY_SHORT[r.safety_status] || '—') + '</span>';
  }

  function interactionDetailRows(rows) {
    return rows.map(function (r) {
      var s = r.screenshots || {};
      var shot = s.highlighted || s.before || s.after;
      return [esc(r.label || '—') + '<small>' + esc(r.page_path) + (r.destination ? ' → ' + esc(shortDest(r)) : '') + '</small>',
        chip('type', r.type_label),
        (r.safety_status === 'not_executed'
          ? chip('skipped', 'Not tested') + '<small>' + esc(r.safety_reason || '') + '</small>'
          : testChip(r.test_status)),
        (analyticsKey(r) === 'safety_restricted' ? '<span class="jr-muted">—</span>' : analyticsChip(r)),
        shot ? '<a class="jr-thumb" href="' + esc(img(shot)) + '" target="_blank" rel="noopener" title="Open screenshot"><img src="' + esc(img(shot)) + '" alt="Screenshot of ' + esc(r.label || '') + '" loading="lazy"></a>' : '<span class="jr-muted">No screenshot</span>'];
    });
  }

  function renderInteractions(el, view, onPick, startFilter) {
    var all = (view.interactions || []).slice().sort(function (a, b) {
      return (isTested(a) ? 0 : 1) - (isTested(b) ? 0 : 1) || (a.index - b.index);
    });
    var current = startFilter || 'tested';
    function draw() {
      var rows = filterInteractions(all, current);
      var shown = rows.slice(0, MAX_INTERACTION_ROWS);
      el.innerHTML = '<div class="jr-filter">' + INTERACTION_FILTERS.map(function (f) {
        var n = filterInteractions(all, f[0]).length;
        if (!n && f[0] !== current && f[0] !== 'tested') return '';
        return '<button type="button" class="jr-filter__btn' + (f[0] === current ? ' is-active' : '') + '" data-filter="' + f[0] + '">' +
          esc(f[1]) + ' <span>' + n + '</span></button>';
      }).join('') + '</div>' +
      (shown.length ? table(['Button / link', 'Type', 'Result', 'Analytics', 'Evidence'], interactionDetailRows(shown),
        function (i) { return ' class="is-clickable" data-index="' + shown[i].index + '"'; })
        : '<p class="jr-muted">Nothing in this group.</p>') +
      (rows.length > shown.length ? '<p class="jr-muted">Showing the first ' + shown.length + ' of ' + rows.length + '.</p>' : '');
      el.querySelectorAll('[data-filter]').forEach(function (b) {
        b.addEventListener('click', function () { current = b.getAttribute('data-filter'); draw(); });
      });
      el.querySelectorAll('tr[data-index]').forEach(function (tr) {
        tr.addEventListener('click', function (e) {
          if (e.target.closest('a')) return;
          onPick(parseInt(tr.getAttribute('data-index'), 10));
        });
      });
    }
    if (!all.length) { el.innerHTML = '<p class="jr-muted">No buttons or links were found in this scan.</p>'; return; }
    draw();
  }

  /* Tracking validation */
  function renderCoverage(view) {
    var tr = view.tracking || {};
    var cov = tr.coverage_by_type || [];
    var vendors = tr.vendors || [];
    var v = tr.validation || {};
    var tiles = [
      ['Analytics Hit Detected', v.analytics_hit, 'pass'], ['DataLayer Event Detected', v.datalayer, v.datalayer ? 'warn' : ''],
      ['Both Detected', v.both, 'pass'], ['Not Detected', v.not_detected, v.not_detected ? 'fail' : ''],
      ['Duplicate Detected', v.duplicate, v.duplicate ? 'warn' : ''], ['Unable to Validate', v.unable, ''],
      ['Not Tested — Safety Restricted', v.safety_restricted, '']
    ];
    return '<p class="jr-muted">For each interaction we recorded analytics requests sent over the network (GA4, Adobe, Piano, Meta…) ' +
      'and dataLayer pushes separately. A DataLayer Event on its own shows the site prepared the data — it does not prove an analytics tool received it.</p>' +
      (tr.validation ? '<div class="jr-tiles">' + tiles.map(function (t) {
        return '<div class="jr-tile"' + (t[2] ? ' data-state="' + t[2] + '"' : '') + '><span class="jr-tile__value">' + esc(t[1] || 0) + '</span><span class="jr-tile__label">' + esc(t[0]) + '</span></div>';
      }).join('') + '</div>' : '') +
      '<p class="jr-muted">Analytics observed during the scan: ' +
      (vendors.length ? vendors.map(function (x) { return esc(x.label) + ' (' + x.hits + ' hits)'; }).join(', ') : 'none') + '.</p>' +
      table(['Interaction type', 'Executed', 'Analytics Hit Detected', 'DataLayer Event only', 'Both Detected', 'Not Detected', 'Duplicate Detected'], cov.map(function (c) {
        var hasSplit = c.analytics_hit != null;
        return [esc(c.type), c.tested, hasSplit ? c.analytics_hit : c.tracked, hasSplit ? c.datalayer_only : '—', hasSplit ? c.both : '—',
          c.not_tracked ? '<strong style="color:var(--color-error)">' + c.not_tracked + '</strong>' : 0, c.duplicate];
      }));
  }

  function renderForms(view) {
    var forms = (view.forms || []).filter(function (f) { return !f.is_search; });
    return '<p class="jr-muted">Forms are discovered and focused, never submitted on production sites.</p>' +
      table(['Form', 'Fields', 'Submit', 'Validation / tracking'], forms.map(function (f) {
        return [esc(f.heading || f.name || 'Form') + '<small>' + esc(f.page_url) + '</small>',
          esc(f.visible_fields) + ' visible · ' + esc(f.required_fields) + ' required · ' + esc(f.hidden_fields) + ' hidden' +
            '<small>' + esc((f.fields || []).filter(function (x) { return x.visible; }).map(function (x) { return x.label || x.name; }).join(', ')) + '</small>',
          esc((f.submit_controls || []).join(', ') || '—') + '<small>' + esc((f.method || '').toUpperCase()) + ' ' + esc(f.action || '') + '</small>',
          esc(f.validation || '') + '<small>' + esc((f.tracking_hints || []).length ? 'Tracking hints: ' + f.tracking_hints.join(', ') : 'No tracking hint on the form element') + '</small>'];
      }));
  }

  var SEV_CHIP = { critical: 'failed', warning: 'skipped', info: '' };
  var SEV_GROUPS = [['critical', 'Fix now'], ['warning', 'Fix soon'], ['info', 'Good to know']];

  function issueItem(x) {
    var j = x.journey || {};
    var idx = j.interaction_index;
    var page = j.page || (x.affected_urls || [])[0];
    var path = '';
    try { path = page ? new URL(page).pathname : ''; } catch (e) { path = page || ''; }
    return '<li class="jr-issue">' +
      '<span class="jr-issue__title">' + esc(x.title) + '</span>' +
      (x.description ? '<span class="jr-issue__text">' + esc(x.description) + '</span>' : '') +
      (x.recommendation ? '<span class="jr-issue__fix"><strong>Fix:</strong> ' + esc(x.recommendation) + '</span>' : '') +
      '<span class="jr-issue__meta">' + (path ? 'Page ' + esc(path) : '') +
        (idx != null ? ' <button type="button" class="jr-link" data-show-index="' + esc(idx) + '">Show evidence</button>' : '') + '</span>' +
      '</li>';
  }

  function renderFindings(view) {
    var f = view.findings || [];
    var accepted = (view.accepted_findings || []).length;
    var note = accepted ? '<p class="jr-muted">' + accepted + ' finding' + (accepted === 1 ? '' : 's') +
      ' marked as intentional by the site\'s team ' + (accepted === 1 ? 'is' : 'are') + ' left out (see Accepted findings in the report).</p>' : '';
    if (!f.length) return note + '<p class="jr-note">No Journey Map issues were found in this scan.</p>';
    return note + SEV_GROUPS.map(function (g) {
      var items = f.filter(function (x) { return (x.severity || 'info') === g[0]; });
      if (!items.length) return '';
      var head = chip(SEV_CHIP[g[0]], g[1]) + ' <span class="jr-muted">' + items.length + '</span>';
      var list = '<ul class="jr-issues">' + items.map(issueItem).join('') + '</ul>';
      return g[0] === 'info'
        ? '<details class="jr-group"><summary>' + head + '</summary>' + list + '</details>'
        : '<div class="jr-group"><p class="jr-group__head">' + head + '</p>' + list + '</div>';
    }).join('');
  }

  /* Summary strip at the top: score, four numbers, top fixes. */
  function renderOverview(view) {
    var c = view.counts || {};
    var o = view.overview || {};
    var pages = (view.page_rows || view.pages || []).length || c.pages_scanned || 0;
    // Same count as the "not tracked" lines in Pages checked (important actions that worked but sent nothing).
    var notTracked = (view.page_rows || []).reduce(function (n, p) { return n + (p.not_tracked || 0); }, 0);
    var stats = [
      [pages, 'pages checked', ''],
      [c.interactions_tested || 0, 'clicks tested', ''],
      [c.successful_interactions || 0, 'worked', (c.interactions_tested && c.successful_interactions === c.interactions_tested) ? 'pass' : ''],
      [notTracked, 'not tracked', notTracked ? 'fail' : 'pass']
    ];
    var fix = (o.fix_first || []).slice(0, 3);
    return '<div class="jr-strip">' +
      '<div class="jr-strip__score" data-band="' + band(view.score) + '"><span class="jr-strip__value">' +
        (view.score == null ? '—' : view.score) + '<small>/100</small></span><span class="jr-strip__label">Journey score</span></div>' +
      '<div class="jr-strip__stats">' + stats.map(function (t) {
        return '<div class="jr-stat"' + (t[2] ? ' data-state="' + t[2] + '"' : '') + '><span class="jr-stat__value">' + esc(t[0]) +
          '</span><span class="jr-stat__label">' + esc(t[1]) + '</span></div>';
      }).join('') + '</div></div>' +
      (fix.length ? '<div class="jr-fixfirst"><p class="jr-fixfirst__h">Fix first' +
          ((o.issues_total || 0) > fix.length ? ' <span class="jr-muted">(top ' + fix.length + ' of ' + o.issues_total + ' — all in Issues)</span>' : '') +
          '</p><ol>' + fix.map(function (f) {
            return '<li>' + chip(SEV_CHIP[f.severity], f.severity === 'critical' ? 'Fix now' : 'Fix soon') + ' <strong>' + esc(f.title) + '</strong></li>';
          }).join('') + '</ol></div>'
        : '<p class="jr-note" style="margin-top:10px;">Nothing urgent: no Fix now or Fix soon issues in this scan.</p>');
  }

  /* Pages checked: one row per page, its clicks inside. */
  function renderPages(el, view, onPick) {
    var pages = view.page_rows || [];
    if (!pages.length) { el.innerHTML = '<p class="jr-muted">No pages were recorded in this scan.</p>'; return; }
    var byIndex = {};
    (view.interactions || []).forEach(function (r) { byIndex[r.index] = r; });
    el.innerHTML = '<div class="jr-pages">' + pages.map(function (p) {
      var http = p.error ? chip('failed', 'Error') : (p.status ? chip(p.ok ? 'success' : 'failed', 'HTTP ' + p.status) : chip('', '—'));
      var issues = (p.issues_critical ? chip('failed', p.issues_critical + ' Fix now') : '') +
        (p.issues_warning ? chip('skipped', p.issues_warning + ' Fix soon') : '');
      var ints = (p.interaction_indexes || []).map(function (i) { return byIndex[i]; }).filter(function (r) { return r && isTested(r); });
      var body = ints.length
        ? table(['Button / link', 'Type', 'Result', 'Analytics', 'Evidence'], interactionDetailRows(ints),
            function (i) { return ' class="is-clickable" data-index="' + ints[i].index + '"'; })
        : '<p class="jr-muted">No buttons or links were tested on this page' +
            (p.elements ? ' (' + p.elements + ' found; repeats of elements already tested elsewhere, like the main menu, are tested once).' : '.') + '</p>';
      return '<details class="jr-page" data-page="' + p.n + '"><summary class="jr-page__row">' +
        '<span class="jr-page__n">' + p.n + '</span>' +
        '<span class="jr-page__name"><strong>' + esc(p.title || p.path) + '</strong><small>' + esc(p.path) +
          (p.redirected ? ' → ' + esc(p.final_url) : '') + '</small></span>' +
        '<span class="jr-page__http">' + http + '</span>' +
        '<span class="jr-page__tested">' + (p.tested ? p.worked + ' of ' + p.tested + ' worked' : '<span class="jr-muted">none tested</span>') +
          (p.not_tracked ? '<small>' + p.not_tracked + ' not tracked</small>' : '') + '</span>' +
        '<span class="jr-page__issues">' + (issues || '<span class="jr-muted">No issues</span>') + '</span>' +
        '</summary><div class="jr-page__body">' +
          (p.via ? '<p class="jr-muted">Reached via “' + esc(p.via) + '”' + (p.analytics_on_load.length ? ' · Analytics on load: ' + esc(p.analytics_on_load.slice(0, 4).join(', ')) : '') + '</p>' : '') +
          '<div class="jr-page__grid">' +
            (p.screenshot ? '<a class="jr-page__shot" href="' + esc(img(p.screenshot)) + '" target="_blank" rel="noopener"><img src="' + esc(img(p.screenshot)) + '" alt="Screenshot of ' + esc(p.title || p.path) + '" loading="lazy"><span>Full page</span></a>'
              : '<div class="jr-page__shot jr-page__shot--none">No page screenshot</div>') +
            '<div>' + body + '</div></div>' +
          '<aside class="jr-detail jr-detail--inline" hidden></aside></div></details>';
    }).join('') + '</div>';
    el.querySelectorAll('.jr-page').forEach(function (d) {
      var aside = d.querySelector('.jr-detail');
      d.querySelectorAll('tr[data-index]').forEach(function (tr) {
        tr.addEventListener('click', function (e) {
          if (e.target.closest('a')) return;
          aside.innerHTML = onPick(parseInt(tr.getAttribute('data-index'), 10));
          aside.hidden = false;
        });
      });
    });
  }


  /* Screenshots: every page and every tested click, as before. */
  function renderGallery(el, view, onPick) {
    var pages = view.page_rows || [];
    var rows = (view.interactions || []).filter(function (r) {
      var s = r.screenshots || {}; return isTested(r) && (s.highlighted || s.before || s.after);
    });
    var current = 'all';
    function draw() {
      var pageShots = pages.filter(function (p) { return p.screenshot && (current === 'all' || p.path === current); });
      var clickShots = rows.filter(function (r) { return current === 'all' || r.page_path === current; });
      var opts = [['all', 'All pages']].concat(pages.map(function (p) { return [p.path, p.title || p.path]; }));
      el.innerHTML = '<div class="jr-filter"><label class="jr-muted">Page&nbsp;<select class="jr-select">' + opts.map(function (o) {
          return '<option value="' + esc(o[0]) + '"' + (o[0] === current ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
        }).join('') + '</select></label><span class="jr-muted">' + pageShots.length + ' page and ' + clickShots.length + ' click screenshots</span></div>' +
        (pageShots.length ? '<p class="jr-title">Pages</p><div class="jr-gallery">' + pageShots.map(function (p) {
          return '<div class="jr-card"><a href="' + esc(img(p.screenshot)) + '" target="_blank" rel="noopener"><img src="' + esc(img(p.screenshot)) + '" alt="' + esc(p.title || p.path) + '" loading="lazy"></a>' +
            '<span class="jr-card__title">' + esc(p.title || p.path) + '</span>' +
            '<span class="jr-card__meta">' + (p.status ? chip(p.ok ? 'success' : 'failed', 'HTTP ' + p.status) : '') + '<span class="jr-muted" style="font-size:12px;">' + esc(p.path) + '</span></span></div>';
        }).join('') + '</div>' : '') +
        (clickShots.length ? '<p class="jr-title" style="margin-top:12px;">Clicks — highlighted element, with before and after</p><div class="jr-gallery">' + clickShots.map(function (r) {
          var s = r.screenshots || {};
          var main = s.highlighted || s.before || s.after;
          var links = ['before', 'highlighted', 'after', 'form'].filter(function (k) { return s[k]; }).map(function (k) {
            return '<a href="' + esc(img(s[k])) + '" target="_blank" rel="noopener">' + esc(k) + '</a>';
          }).join(' · ');
          return '<div class="jr-card is-clickable" data-index="' + r.index + '"><img src="' + esc(img(main)) + '" alt="' + esc(r.label) + '" loading="lazy">' +
            '<span class="jr-card__title">' + esc(r.label) + '</span>' +
            '<span class="jr-card__meta">' + chip('type', r.type_label) + testChip(r.test_status) + analyticsChip(r) + '</span>' +
            '<span class="jr-muted" style="font-size:12px;">' + esc(r.page_path) + ' · ' + links + '</span></div>';
        }).join('') + '</div>' : '<p class="jr-muted">No click screenshots for this page.</p>');
      var sel = el.querySelector('.jr-select');
      if (sel) sel.addEventListener('change', function () { current = sel.value; draw(); });
      el.querySelectorAll('.jr-card[data-index]').forEach(function (c) {
        c.addEventListener('click', function (e) { if (e.target.closest('a')) return; onPick(parseInt(c.getAttribute('data-index'), 10)); });
      });
    }
    if (!rows.length && !pages.some(function (p) { return p.screenshot; })) { el.innerHTML = '<p class="jr-muted">No screenshots were captured in this scan.</p>'; return; }
    draw();
  }

  /* How this audit works (folded). */
  function renderHow(view) {
    var o = view.overview || {};
    return '<ol class="jr-ov__did">' + (o.did || []).map(function (d) { return '<li>' + esc(d) + '</li>'; }).join('') + '</ol>' +
      ((o.coverage || []).length ? '<p><strong>How complete is this scan?</strong> ' + esc(o.coverage.join(' ')) + '</p>' : '') +
      ((view.test_method || []).length ? '<p class="jr-title">How each click was tested</p><ol class="jr-steps-list">' +
        view.test_method.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('') + '</ol>' : '') +
      '<p class="jr-title">How the score is calculated</p>' + renderHealth(view) +
      '<p class="jr-muted" style="margin-top:8px;">' + esc(view.provenance || '') + '</p>';
  }

  /* Public */
  function renderReport(journey, ids) {
    var get = function (id) { return document.getElementById(id); };
    var set = function (id, html) { var el = id && get(id); if (el) el.innerHTML = html; return el; };
    var content = get(ids.content), empty = get(ids.empty);
    var view = journey && journey.reportView;
    if (!view) {
      if (empty) { empty.textContent = "This audit didn't include the Journey Map module."; empty.style.display = ''; }
      if (content) content.style.display = 'none';
      return null;
    }
    if (!view.available) {
      if (empty) { empty.textContent = 'The journey map scan could not run: ' + (view.error || 'the scan stopped without an error message (most likely the time limit). Please run the audit again.'); empty.style.display = ''; }
      if (content) content.style.display = 'none';
      return view;
    }
    if (empty) empty.style.display = 'none';
    content.style.display = '';
    var notice = '';
    var tested = ((view.counts || {}).interactions_tested) || 0;
    if (view.error) {
      notice = '<p class="jr-notice" role="status"><strong>Scan note:</strong> ' + esc(view.error) + '</p>';
    } else if (!tested && ((view.counts || {}).interactions_discovered || 0) > 0) {
      notice = '<p class="jr-notice" role="status"><strong>Scan note:</strong> buttons and links were found but none could be clicked in this run, so no Journey score was calculated. Please run the audit again.</p>';
    }
    set(ids.overview, renderOverview(view));
    set(ids.health, notice);

    // Evidence for one click (built on demand, so screenshots load only when opened).
    var detailFor = function (index) {
      var nid = nodeIdForIndex(view, index);
      view.map = view.map || {};
      view.map.nodes = view.map.nodes || {};
      if (!view.map.nodes[nid]) {
        var row = (view.interactions || []).filter(function (r) { return r.index === index; })[0];
        if (!row) return '';
        view.map.nodes[nid] = { kind: 'interaction', index: index, label: row.label, path: row.page_path, type_label: row.type_label };
      }
      return renderDetail(view, nid);
    };

    // Tabs
    var showTab = function (name) {
      content.querySelectorAll('[data-jtab]').forEach(function (b) {
        var on = b.getAttribute('data-jtab') === name;
        b.classList.toggle('is-active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      content.querySelectorAll('[data-jpane]').forEach(function (p) { p.hidden = p.getAttribute('data-jpane') !== name; });
    };
    content.querySelectorAll('[data-jtab]').forEach(function (b) {
      b.onclick = function () { showTab(b.getAttribute('data-jtab')); };
    });
    showTab('pages');
    var count = function (name, n) { var el = get('jtabCount-' + name); if (el) el.textContent = n == null ? '' : n; };
    var issuesN = (view.findings || []).filter(function (f) { return f.severity === 'critical' || f.severity === 'warning'; }).length;
    count('pages', (view.page_rows || []).length);
    count('issues', issuesN);
    count('paths', ((view.map || {}).journeys || []).length);
    count('clicks', tested);

    // Pages checked
    var pagesEl = get(ids.pages);
    if (pagesEl) renderPages(pagesEl, view, detailFor);

    // Journey paths
    var mapEl = get(ids.map), detailEl = get(ids.detail);
    if (mapEl && detailEl) {
      mapEl.innerHTML = renderMap(view);
      var firstJourney = ((view.map || {}).journeys || [])[0];
      detailEl.innerHTML = firstJourney ? renderDetail(view, firstJourney.steps[firstJourney.steps.length - 1])
        : '<p class="jr-muted">Select a step to see its evidence.</p>';
      wireMap(mapEl, detailEl, view);
    }

    // All clicks
    var clickDetail = get(ids.clickDetail);
    var pick = function (index) {
      if (!clickDetail) return;
      clickDetail.innerHTML = detailFor(index);
      clickDetail.hidden = false;
      clickDetail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };
    var inter = get(ids.interactions);
    if (inter) renderInteractions(inter, view, pick);
    var galleryEl = get(ids.gallery), galleryDetail = get(ids.galleryDetail);
    if (galleryEl) renderGallery(galleryEl, view, function (index) {
      if (!galleryDetail) return;
      galleryDetail.innerHTML = detailFor(index);
      galleryDetail.hidden = false;
      galleryDetail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
    var shotCount = (view.interactions || []).filter(function (r) { var x = r.screenshots || {}; return isTested(r) && (x.highlighted || x.before || x.after); }).length +
      (view.page_rows || []).filter(function (p) { return p.screenshot; }).length;
    count('shots', shotCount);

    // Issues: "Show evidence" opens the click in All clicks.
    var issuesEl = set(ids.findings, renderFindings(view));
    if (issuesEl) issuesEl.addEventListener('click', function (e) {
      var b = e.target.closest('[data-show-index]');
      if (!b) return;
      showTab('clicks');
      pick(parseInt(b.getAttribute('data-show-index'), 10));
    });

    // How this audit works (folded)
    set(ids.how, renderHow(view));
    set(ids.coverage, renderCoverage(view));
    set(ids.summary, renderSummary(view));
    set(ids.forms, renderForms(view));
    return view;
  }

  function renderDashboardCard(journey, link) {
    var card = document.getElementById('journeyHealthCard');
    var view = journey && journey.reportView;
    if (!card || !view || !view.available) return false;
    var c = view.counts || {};
    var badge = document.getElementById('journeyHealthBadge');
    var gaps = c.tracking_gaps || 0;
    badge.className = 'badge ' + (gaps ? 'badge--error' : 'badge--success');
    badge.textContent = gaps ? gaps + ' tracking gap' + (gaps === 1 ? '' : 's') : 'No tracking gaps detected';
    var journeys = (view.map || {}).journeys || [];
    var v = (view.tracking || {}).validation || {};
    var tiles = [['Journey paths found', journeys.length], ['Interactions found', c.interactions_discovered], ['Executed', c.interactions_tested],
      ['Analytics Hit Detected', (v.analytics_hit || 0) + (v.both || 0)], ['DataLayer Event only', v.datalayer || 0],
      ['Tracking gaps', gaps, gaps ? 'fail' : 'pass'], ['Journey Health', view.score == null ? '—' : view.score + '/100']];
    var nodes = (view.map || {}).nodes || {};
    var flows = journeys.slice(0, 3).map(function (j) { return journeyFlow(j, nodes, false); }).join('');
    document.getElementById('journeyHealthBody').innerHTML =
      '<div class="jr-tiles">' + tiles.map(function (t) {
        return '<div class="jr-tile"' + (t[2] ? ' data-state="' + t[2] + '"' : '') + '><span class="jr-tile__value">' + esc(t[1] == null ? 0 : t[1]) + '</span><span class="jr-tile__label">' + esc(t[0]) + '</span></div>';
      }).join('') + '</div>' +
      (flows ? '<p class="jr-muted" style="margin:12px 0 4px;">Discovered Journey Paths (most critical first)</p><div class="jr-flows">' + flows + '</div>' : '');
    document.getElementById('journeyHealthLink').href = link + '#journey';
    card.querySelectorAll('[data-node]').forEach(function (b) { b.addEventListener('click', function () { window.location.href = link + '#journey'; }); });
    card.style.display = '';
    return true;
  }

  window.JourneyRender = { renderReport: renderReport, renderDashboardCard: renderDashboardCard };
})();
