/* ==========================================================================
   journey-render.js — Customer Journey UI (report page section + dashboard
   card). Renders JourneyOut.report_view (backend reports/journey_view.py)
   exactly as the backend built it: nothing here invents a step, a status or
   a number. Exposes window.JourneyRender.
   ========================================================================== */

(function () {
  var U = window.Utils;
  var esc = function (v) { return U.escapeHtml(v == null ? '' : String(v)); };

  // Analytics result per interaction (reports/journey_view.analytics_result):
  // what was actually observed, never inferred.
  var ANALYTICS_CHIP = {
    both: ['tracked', 'Analytics hit + DataLayer event'],
    analytics_hit: ['tracked', 'Analytics hit detected'],
    datalayer: ['datalayer', 'DataLayer event detected'],
    detected: ['tracked', 'Tracking event detected'],
    duplicate: ['duplicate', 'Duplicate detected'],
    not_detected: ['not_tracked', 'Not detected'],
    unable: ['not_tested', 'Unable to validate'],
    not_applicable: ['not_applicable', '—']
  };
  var LEGACY_TRACK = { tracked: 'detected', not_tracked: 'not_detected', duplicate: 'duplicate', not_applicable: 'not_applicable' };
  var TEST_CHIP = {
    success: ['success', 'Worked'], failed: ['failed', 'Failed'],
    skipped: ['skipped', 'Not executed (safety)'], not_tested: ['', 'Discovered, not executed'],
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

  /* ------------------------------ health ------------------------------ */
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
    return '<div class="jr-health">' +
      '<div class="jr-score" data-band="' + band(view.score) + '">' +
        '<span class="jr-score__value">' + (view.score == null ? '—' : view.score) + '</span>' +
        '<span class="jr-score__label">Technical journey health</span></div>' +
      '<div>' +
        (parts ? '<p class="jr-muted" style="margin:0 0 6px;">How the score was calculated from this scan: ' + esc(ex.formula || '') + '.</p>' +
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

  /* ------------------------------ map ------------------------------ */
  function stepButton(node, nid) {
    if (!node) return '';
    if (node.kind === 'page') {
      return '<button type="button" class="jr-step jr-step--page" data-node="' + esc(nid) + '">' +
        '<span class="jr-step__kind">Page</span><span class="jr-step__label">' + esc(node.path) + '</span></button>';
    }
    var a = analyticsKey(node);
    var trk = { both: 'tracked', analytics_hit: 'tracked', detected: 'tracked', datalayer: 'datalayer', duplicate: 'duplicate',
      not_detected: 'not_tracked', unable: 'not_tested', not_applicable: 'not_tested' }[a] || 'not_tested';
    if (trk === 'not_tracked' && node.test_status !== 'success') trk = 'not_tested';   // failed steps aren't tracking gaps
    return '<button type="button" class="jr-step jr-step--interaction" data-node="' + esc(nid) + '" data-tracking="' + esc(trk) + '"' +
      (node.test_status === 'failed' ? ' data-failed="true"' : '') + ' title="' + esc((ANALYTICS_CHIP[a] || ANALYTICS_CHIP.unable)[1]) + '">' +
      '<span class="jr-step__kind">' + esc(node.type_label) + '</span><span class="jr-step__label">' + esc(node.label) + '</span></button>';
  }

  function renderTree(nodes, tree) {
    function li(t) {
      var n = nodes[t.node] || {};
      var ints = (t.interactions || []).map(function (id) { return stepButton(nodes[id], id); }).join('');
      return '<li><div class="jr-tree__row">' + stepButton(n, t.node) +
        (ints ? '<span class="jr-tree__ints">' + ints + '</span>' : '') + '</div>' +
        ((t.children || []).length ? '<ul>' + t.children.map(li).join('') + '</ul>' : '') + '</li>';
    }
    return '<ul class="jr-tree">' + (tree || []).map(li).join('') + '</ul>';
  }

  function journeyFlow(j, nodes, compact) {
    var meta = compact ? '' :
      '<span class="jr-flow__meta">' + chip('type', j.goal_type_label || '') + importanceChip(j.importance) +
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
    var pages = Object.keys(nodes).filter(function (k) { return nodes[k].kind === 'page'; }).length;
    return '<p class="jr-provenance">' + esc(view.provenance || '') + '</p>' +
      '<div class="jr-legend"><span class="l-tracked">Analytics hit detected</span><span class="l-dl">DataLayer event only</span>' +
      '<span class="l-gap">Executed, nothing detected</span><span class="l-dup">Duplicate detected</span>' +
      '<span>Unable to validate (not executed)</span><span class="l-gap">Dashed = interaction failed</span></div>' +
      '<p class="jr-title" style="margin-top:4px;">Discovered journey paths (' + journeys.length + ')</p>' +
      (journeys.length ? '<p class="jr-muted" style="margin-top:0;">Most critical first: broken steps, then tracking gaps, then by importance of the goal.</p>' : '') +
      '<div class="jr-flows">' + (flows || '<p class="jr-muted">No journey path was discovered in this scan — no conversion-type interaction (CTA, form, download, signup, booking, purchase, phone or email link) was found on the scanned pages.</p>') + '</div>' +
      '<details class="jr-structure"><summary class="jr-title" style="cursor:pointer;">Supporting information: site structure (' + pages + ' page' + (pages === 1 ? '' : 's') + ')</summary>' +
      renderTree(nodes, map.site_tree) + '</details>';
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
    return '<h4>' + esc(row.label || n.label) + '</h4><dl>' +
      '<dt>Type</dt><dd>' + chip('type', row.type_label || n.type_label) + importanceChip(row.importance) + '</dd>' +
      '<dt>Page</dt><dd>' + esc(row.page_path || n.path) + '</dd>' +
      (row.destination ? '<dt>Destination</dt><dd>' + esc(row.destination) + '</dd>' : '') +
      '<dt>Test result</dt><dd>' + testChip(row.test_status || n.test_status) + '</dd>' +
      '<dt>Safety</dt><dd>' + esc(row.safety_label || '—') + '</dd>' +
      '<dt>Observed</dt><dd>' + esc(row.observed || n.observed || '—') + '</dd>' +
      '<dt>Analytics</dt><dd>' + analyticsChip(row) +
        ((row.tracking_events || []).length ? '<br>' + esc(row.tracking_events.join(', ')) : '') +
        (row.analytics_reason ? '<br><small>' + esc(row.analytics_reason) + '</small>' :
          (row.tracking_note ? '<br><small>' + esc(row.tracking_note) + '</small>' : '')) + '</dd>' +
      '<dt>Signals</dt><dd>' + esc((row.signals || []).join(' · ') || '—') + '</dd>' +
      ((n.issues || []).length ? '<dt>Issues</dt><dd>' + n.issues.map(function (i) { var f = (view.findings || [])[i]; return f ? esc(f.title) : ''; }).join('<br>') + '</dd>' : '') +
      '</dl>' + (shotHtml ? '<div class="jr-shots">' + shotHtml + '</div>' : '<p class="jr-muted">No screenshot was captured for this interaction.</p>');
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

  /* ------------------------------ interaction details ------------------------------ */
  var INTERACTION_FILTERS = [
    ['all', 'All discovered'], ['executed', 'Executed'], ['not_executed', 'Not executed (safety)'],
    ['failed', 'Failed'], ['gap', 'Executed, no tracking detected'], ['datalayer', 'DataLayer only']
  ];
  var MAX_INTERACTION_ROWS = 200;

  function filterInteractions(rows, f) {
    return rows.filter(function (r) {
      if (f === 'executed') return r.test_status === 'success' || r.test_status === 'failed';
      if (f === 'not_executed') return r.safety_status === 'not_executed';
      if (f === 'failed') return r.test_status === 'failed';
      if (f === 'gap') return r.test_status === 'success' && analyticsKey(r) === 'not_detected';
      if (f === 'datalayer') return analyticsKey(r) === 'datalayer';
      return true;
    });
  }

  function shortDest(r) {
    var d = r.destination || '';
    try {
      var u = new URL(d, r.page || undefined), p = new URL(r.page);
      if (u.host === p.host && /^https?:$/.test(u.protocol)) return (u.pathname || '/') + u.search;
    } catch (e) { /* not a URL (tel:, mailto:, javascript) */ }
    return d;
  }

  var SAFETY_SHORT = { executed: 'Executed', checked: 'HTTP check only', not_executed: 'Not executed (safety)',
    consent: 'Consent control', repeat: 'Repeat element', not_selected: 'Not selected for test' };
  function safetyCell(r) {
    var short = SAFETY_SHORT[r.safety_status] || '—';
    var reason = r.safety_status === 'not_executed' ? (r.safety_label || '').replace(/^Not executed — /, '') : '';
    return '<span title="' + esc(r.safety_label || '') + '">' + esc(short) + '</span>' + (reason ? '<small>' + esc(reason) + '</small>' : '');
  }

  function interactionDetailRows(rows) {
    return rows.map(function (r) {
      var s = r.screenshots || {};
      var shot = s.highlighted || s.before || s.after;
      return [esc(r.label || '—') + '<small>' + esc(r.page_path) + '</small>',
        chip('type', r.type_label),
        r.destination ? '<span class="jr-dest" title="' + esc(r.destination) + '">' + esc(shortDest(r)) + '</span>' : '—',
        testChip(r.test_status) + (r.observed ? '<small>' + esc(r.observed) + '</small>' : ''),
        safetyCell(r),
        analyticsChip(r) + ((r.tracking_events || []).length ? '<small>' + esc(r.tracking_events.join(', ')) + '</small>' : ''),
        shot ? '<a class="jr-nowrap" href="' + esc(img(shot)) + '" target="_blank" rel="noopener">View</a>' : '<span class="jr-muted">—</span>'];
    });
  }

  function renderInteractions(el, view, onPick) {
    var all = (view.interactions || []).slice().sort(function (a, b) {
      var ea = (a.test_status === 'success' || a.test_status === 'failed') ? 0 : 1;
      var eb = (b.test_status === 'success' || b.test_status === 'failed') ? 0 : 1;
      return ea - eb || (a.index - b.index);
    });
    var current = 'all';
    function draw() {
      var rows = filterInteractions(all, current);
      var shown = rows.slice(0, MAX_INTERACTION_ROWS);
      el.innerHTML = '<div class="jr-filter">' + INTERACTION_FILTERS.map(function (f) {
        var n = filterInteractions(all, f[0]).length;
        return '<button type="button" class="jr-filter__btn' + (f[0] === current ? ' is-active' : '') + '" data-filter="' + f[0] + '">' +
          esc(f[1]) + ' <span>' + n + '</span></button>';
      }).join('') + '</div>' +
      '<div class="jr-wide">' + table(['Interaction', 'Type', 'Destination', 'Test result', 'Safety', 'Analytics', 'Evidence'], interactionDetailRows(shown),
        function (i) { return ' class="is-clickable" data-index="' + shown[i].index + '"'; }) + '</div>' +
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
    if (!all.length) { el.innerHTML = '<p class="jr-muted">No interactive elements were discovered in this scan.</p>'; return; }
    draw();
  }

  /* ------------------------------ analytics validation ------------------------------ */
  function renderCoverage(view) {
    var tr = view.tracking || {};
    var cov = tr.coverage_by_type || [];
    var vendors = tr.vendors || [];
    var v = tr.validation || {};
    var tiles = [
      ['Analytics hit detected', v.analytics_hit, 'pass'], ['DataLayer event detected', v.datalayer, v.datalayer ? 'warn' : ''],
      ['Both detected', v.both, 'pass'], ['Not detected', v.not_detected, v.not_detected ? 'fail' : ''],
      ['Duplicate detected', v.duplicate, v.duplicate ? 'warn' : ''], ['Unable to validate', v.unable, '']
    ];
    return '<p class="jr-muted">For each interaction we recorded analytics requests sent over the network (GA4, Adobe, Piano, Meta…) ' +
      'and dataLayer pushes separately. A dataLayer event alone shows the site prepared the data — it does not prove an analytics tool received it.</p>' +
      (tr.validation ? '<div class="jr-tiles">' + tiles.map(function (t) {
        return '<div class="jr-tile"' + (t[2] ? ' data-state="' + t[2] + '"' : '') + '><span class="jr-tile__value">' + esc(t[1] || 0) + '</span><span class="jr-tile__label">' + esc(t[0]) + '</span></div>';
      }).join('') + '</div>' : '') +
      '<p class="jr-muted">Analytics observed during the scan: ' +
      (vendors.length ? vendors.map(function (x) { return esc(x.label) + ' (' + x.hits + ' hits)'; }).join(', ') : 'none') + '.</p>' +
      table(['Interaction type', 'Executed', 'Analytics hit', 'DataLayer only', 'Both', 'Not detected', 'Duplicate'], cov.map(function (c) {
        var hasSplit = c.analytics_hit != null;
        return [esc(c.type), c.tested, hasSplit ? c.analytics_hit : c.tracked, hasSplit ? c.datalayer_only : '—', hasSplit ? c.both : '—',
          c.not_tracked ? '<strong style="color:var(--color-error)">' + c.not_tracked + '</strong>' : 0, c.duplicate];
      }));
  }

  function interactionRows(rows) {
    return rows.map(function (r) {
      return [esc(r.label) + '<small>' + esc(r.page_path) + '</small>', chip('type', r.type_label), testChip(r.test_status) + (r.observed ? '<small>' + esc(r.observed) + '</small>' : ''),
        analyticsChip(r) + ((r.tracking_events || []).length ? '<small>' + esc(r.tracking_events.join(', ')) + '</small>' : '')];
    });
  }

  function clickableRows(container, rows, onPick) {
    container.querySelectorAll('tr[data-index]').forEach(function (tr) {
      tr.addEventListener('click', function () { onPick(parseInt(tr.getAttribute('data-index'), 10)); });
    });
  }

  function renderGaps(view) {
    var gaps = view.gaps || [];
    if (!gaps.length) return '<p class="jr-muted">No tracking gaps: every conversion interaction that worked when executed produced an analytics hit or dataLayer event.</p>';
    return '<p class="jr-muted">Each of these was discovered and executed successfully, but neither an analytics hit nor a dataLayer event was observed.</p>' +
      table(['Interaction', 'Type', 'Test result', 'Analytics'], interactionRows(gaps), function (i) { return ' class="is-clickable" data-index="' + gaps[i].index + '"'; });
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

  function renderDownloads(view) {
    var d = view.downloads || [];
    return table(['Download', 'Type', 'Resource', 'Analytics'], d.map(function (x) {
      return [esc(x.label) + '<small>' + esc(x.destination) + '</small>', esc((x.file_type || '').toUpperCase() || '—'),
        x.http_status ? (x.accessible ? chip('success', 'HTTP ' + x.http_status) : chip('failed', 'HTTP ' + x.http_status)) : chip('', 'Not checked'),
        x.row ? analyticsChip(x.row) : trackChip(x.tracking)];
    }), function (i) { return ' class="is-clickable" data-index="' + d[i].index + '"'; });
  }

  function renderCtas(view) {
    var c = view.ctas || [];
    return table(['CTA', 'Type', 'Test result', 'Analytics'], interactionRows(c), function (i) { return ' class="is-clickable" data-index="' + c[i].index + '"'; });
  }

  function renderEvidence(view) {
    var ev = (view.evidence || []).filter(function (r) { return (r.screenshots || {}).highlighted || (r.screenshots || {}).before; });
    if (!ev.length) return '<p class="jr-muted">No screenshots were captured in this scan.</p>';
    return '<p class="jr-muted">Each screenshot belongs to the interaction named under it and was taken while executing it.</p><div class="jr-gallery">' + ev.map(function (r) {
      var s = r.screenshots || {};
      var main = s.highlighted || s.before;
      var links = ['before', 'highlighted', 'after', 'form'].filter(function (k) { return s[k]; }).map(function (k) {
        return '<a href="' + esc(img(s[k])) + '" target="_blank" rel="noopener">' + esc(k) + '</a>';
      }).join(' · ');
      return '<div class="jr-card"><a href="' + esc(img(main)) + '" target="_blank" rel="noopener"><img src="' + esc(img(main)) + '" alt="' + esc(r.label) + '" loading="lazy"></a>' +
        '<span class="jr-card__title">#' + r.index + ' ' + esc(r.label) + '</span>' +
        '<span class="jr-card__meta">' + chip('type', r.type_label) + testChip(r.test_status) + analyticsChip(r) + '</span>' +
        '<span class="jr-muted" style="font-size:12px;">' + esc(r.page_path) + ' · ' + links + '</span></div>';
    }).join('') + '</div>';
  }

  var SEV_CHIP = { critical: 'failed', warning: 'skipped', info: '' };

  function renderFindings(view) {
    var f = view.findings || [];
    if (!f.length) return '<p class="jr-muted">No journey issues were detected in this scan.</p>';
    return '<ul class="jr-recs">' + f.map(function (x) {
      var j = x.journey || {};
      return '<li>' + chip(SEV_CHIP[x.severity], x.severity) + '<span><strong>' + esc(x.title) + '</strong><br>' + esc(x.description) +
        (j.tracking_behavior ? '<br><small class="jr-muted">' + esc(j.tracking_behavior) + '</small>' : '') + '</span></li>';
    }).join('') + '</ul>';
  }

  function renderRecs(view) {
    var recs = view.recommendations || [];
    if (!recs.length) return '<p class="jr-muted">No recommendations: no journey issues were detected in this scan.</p>';
    return '<p class="jr-muted">Generated only from the findings above.</p><ul class="jr-recs">' + recs.map(function (r) {
      return '<li>' + chip(SEV_CHIP[r.severity], r.severity) + '<span><strong>' + esc(r.title) + '</strong><br>' + esc(r.recommendation) + '</span></li>';
    }).join('') + '</ul>';
  }

  /* ------------------------------ public ------------------------------ */
  function renderReport(journey, ids) {
    var get = function (id) { return document.getElementById(id); };
    var set = function (id, html) { var el = id && get(id); if (el) el.innerHTML = html; return el; };
    var content = get(ids.content), empty = get(ids.empty);
    var view = journey && journey.reportView;
    if (!view) {
      if (empty) { empty.textContent = "This audit didn't include the Customer Journey module."; empty.style.display = ''; }
      if (content) content.style.display = 'none';
      return null;
    }
    if (!view.available) {
      if (empty) { empty.textContent = 'The customer journey scan could not run: ' + (view.error || 'unknown error'); empty.style.display = ''; }
      if (content) content.style.display = 'none';
      return view;
    }
    if (empty) empty.style.display = 'none';
    content.style.display = '';
    set(ids.health, renderHealth(view));
    set(ids.summary, renderSummary(view));
    var mapEl = get(ids.map), detailEl = get(ids.detail);
    mapEl.innerHTML = renderMap(view);
    var firstJourney = ((view.map || {}).journeys || [])[0];
    var firstGap = (view.gaps || [])[0];
    var initial = firstJourney ? firstJourney.steps[firstJourney.steps.length - 1] : (firstGap ? nodeIdForIndex(view, firstGap.index) : null);
    detailEl.innerHTML = renderDetail(view, initial);
    wireMap(mapEl, detailEl, view);

    var pick = function (index) {
      var nid = nodeIdForIndex(view, index);
      if (!(view.map.nodes || {})[nid]) {
        // Not part of a journey path: show its evidence directly.
        var row = (view.interactions || []).filter(function (r) { return r.index === index; })[0];
        if (!row) return;
        var fake = { kind: 'interaction', index: index, label: row.label, path: row.page_path, type_label: row.type_label };
        view.map.nodes[nid] = fake;
      }
      detailEl.innerHTML = renderDetail(view, nid);
      mapEl.querySelectorAll('.jr-step.is-selected').forEach(function (x) { x.classList.remove('is-selected'); });
      mapEl.querySelectorAll('[data-node="' + nid + '"]').forEach(function (x) { x.classList.add('is-selected'); });
      detailEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };
    var inter = get(ids.interactions);
    if (inter) renderInteractions(inter, view, pick);
    set(ids.coverage, renderCoverage(view));
    var gapsEl = set(ids.gaps, renderGaps(view)); if (gapsEl) clickableRows(gapsEl, view.gaps || [], pick);
    set(ids.forms, renderForms(view));
    var dlEl = set(ids.downloads, renderDownloads(view)); if (dlEl) clickableRows(dlEl, [], pick);
    var ctaEl = set(ids.ctas, renderCtas(view)); if (ctaEl) clickableRows(ctaEl, [], pick);
    set(ids.evidence, renderEvidence(view));
    set(ids.findings, renderFindings(view));
    set(ids.recs, renderRecs(view));
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
    badge.textContent = gaps ? gaps + ' tracking gap' + (gaps === 1 ? '' : 's') : 'Tracking detected on every executed conversion';
    var journeys = (view.map || {}).journeys || [];
    var tiles = [['Journey paths found', journeys.length], ['Interactions found', c.interactions_discovered], ['Executed', c.interactions_tested],
      ['Tracking detected', c.tracked_interactions], ['Tracking gaps', gaps, gaps ? 'fail' : 'pass'], ['Forms', c.forms],
      ['Downloads', c.downloads], ['Journey health', view.score == null ? '—' : view.score]];
    var nodes = (view.map || {}).nodes || {};
    var flows = journeys.slice(0, 3).map(function (j) { return journeyFlow(j, nodes, false); }).join('');
    document.getElementById('journeyHealthBody').innerHTML =
      '<div class="jr-tiles">' + tiles.map(function (t) {
        return '<div class="jr-tile"' + (t[2] ? ' data-state="' + t[2] + '"' : '') + '><span class="jr-tile__value">' + esc(t[1] == null ? 0 : t[1]) + '</span><span class="jr-tile__label">' + esc(t[0]) + '</span></div>';
      }).join('') + '</div>' +
      (flows ? '<p class="jr-muted" style="margin:12px 0 4px;">Discovered journey paths (most critical first)</p><div class="jr-flows">' + flows + '</div>' : '');
    document.getElementById('journeyHealthLink').href = link + '#journey';
    card.querySelectorAll('[data-node]').forEach(function (b) { b.addEventListener('click', function () { window.location.href = link + '#journey'; }); });
    card.style.display = '';
    return true;
  }

  window.JourneyRender = { renderReport: renderReport, renderDashboardCard: renderDashboardCard };
})();
