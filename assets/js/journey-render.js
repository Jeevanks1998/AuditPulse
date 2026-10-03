/* ==========================================================================
   journey-render.js — Customer Journey UI (report page section + dashboard
   card). Renders JourneyOut.report_view (backend reports/journey_view.py)
   exactly as the backend built it: nothing here invents a step, a status or
   a number. Exposes window.JourneyRender.
   ========================================================================== */

(function () {
  var U = window.Utils;
  var esc = function (v) { return U.escapeHtml(v == null ? '' : String(v)); };

  var TRACK_TEXT = {
    tracked: 'Tracked', not_tracked: 'Not detected', duplicate: 'Duplicate event',
    not_tested: 'Not tested', not_applicable: '—'
  };
  var TEST_CHIP = {
    success: ['success', 'Successfully tested'], failed: ['failed', 'Failed'],
    skipped: ['skipped', 'Not executed (safety)'], not_tested: ['', 'Discovered'],
    same_as_first: ['', 'Same as first occurrence'],
    consent_control: ['', 'Consent control']
  };

  function origin() { return (window.APP_CONFIG && window.APP_CONFIG.API_ORIGIN) || ''; }
  function img(url) { return url ? origin() + url : null; }
  function chip(cls, text) { return '<span class="jr-chip' + (cls ? ' jr-chip--' + cls : '') + '">' + esc(text) + '</span>'; }
  function trackChip(st) { return chip(st || 'not_tested', TRACK_TEXT[st] || 'Not tested'); }
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
    var r = view.rates || {};
    var pct = function (v) { return v == null ? '—' : Math.round(v * 100) + '%'; };
    return '<div class="jr-health">' +
      '<div class="jr-score" data-band="' + band(view.score) + '">' +
        '<span class="jr-score__value">' + (view.score == null ? '—' : view.score) + '</span>' +
        '<span class="jr-score__label">Technical journey health</span></div>' +
      '<div><div class="jr-tiles">' + (view.tiles || []).map(function (t) {
        return '<div class="jr-tile"' + (t.state ? ' data-state="' + esc(t.state) + '"' : '') + '>' +
          '<span class="jr-tile__value">' + esc(t.value) + '</span><span class="jr-tile__label">' + esc(t.label) + '</span></div>';
      }).join('') + '</div>' +
      '<div class="jr-rates"><span>Success rate <strong>' + pct(r.success_rate) + '</strong></span>' +
      '<span>Conversion tracking coverage <strong>' + pct(r.conversion_tracking_coverage) + '</strong></span>' +
      '<span>Evidence rate <strong>' + pct(r.evidence_rate) + '</strong></span>' +
      (view.consent_state ? '<span>Consent: <strong>' + esc(view.consent_state) + '</strong></span>' : '') +
      '</div></div></div>';
  }

  function renderSummary(view) {
    var items = view.by_type || [];
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
    var trk = node.tracking_status || 'not_tested';
    if (trk === 'not_tracked' && node.test_status !== 'success') trk = 'not_tested';   // failed steps aren't tracking gaps
    return '<button type="button" class="jr-step jr-step--interaction" data-node="' + esc(nid) + '" data-tracking="' + esc(trk) + '"' +
      (node.test_status === 'failed' ? ' data-failed="true"' : '') + '>' +
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

  function renderMap(view) {
    var map = view.map || {};
    var nodes = map.nodes || {};
    var flows = (map.journeys || []).map(function (j) {
      return '<div class="jr-flow"><span class="jr-flow__name">' + esc(j.name) +
        ((j.tracking_gaps || []).length ? ' · ' + j.tracking_gaps.length + ' tracking gap(s)' : '') + '</span>' +
        '<div class="jr-flow__steps">' + (j.steps || []).map(function (sid, i) {
          return (i ? '<span class="jr-arrow" aria-hidden="true">→</span>' : '') + stepButton(nodes[sid], sid);
        }).join('') + '</div></div>';
    }).join('');
    return '<div class="jr-legend"><span class="l-tracked">Tracked</span><span class="l-gap">Interaction tested, no analytics event</span>' +
      '<span class="l-dup">Duplicate event</span><span>Not tested / not executed</span><span class="l-gap">Dashed = interaction failed</span></div>' +
      '<p class="jr-title" style="margin-top:4px;">Discovered journeys</p>' +
      '<div class="jr-flows">' + (flows || '<p class="jr-muted">No conversion-type interaction was discovered.</p>') + '</div>' +
      '<details><summary class="jr-title" style="cursor:pointer;">Site structure (' + Object.keys(nodes).filter(function (k) { return nodes[k].kind === 'page'; }).length + ' pages)</summary>' +
      renderTree(nodes, map.site_tree) + '</details>';
  }

  function renderDetail(view, nid) {
    var map = view.map || {};
    var n = (map.nodes || {})[nid];
    if (!n) return '<p class="jr-muted">Select a page or interaction in the map to see its evidence.</p>';
    if (n.kind === 'page') {
      return '<h4>' + esc(n.title || n.path) + '</h4><dl>' +
        '<dt>Page</dt><dd>' + esc(n.url) + '</dd>' +
        '<dt>Status</dt><dd>' + esc(n.status || '—') + (n.error ? ' · ' + esc(n.error) : '') + '</dd>' +
        '<dt>Found via</dt><dd>' + esc(n.via_label || (n.parent ? '—' : 'Start page')) + '</dd>' +
        '<dt>Elements</dt><dd>' + esc(n.interaction_count) + '</dd></dl>' +
        (n.screenshot ? '<div class="jr-shots"><a class="jr-shot" href="' + esc(img(n.screenshot)) + '" target="_blank" rel="noopener"><img src="' + esc(img(n.screenshot)) + '" alt="Page screenshot" loading="lazy">Full page</a></div>' : '');
    }
    var row = (view.interactions || []).filter(function (r) { return r.index === n.index; })[0] || {};
    var shots = row.screenshots || {};
    var shotHtml = ['highlighted', 'before', 'after', 'form'].filter(function (k) { return shots[k]; }).map(function (k) {
      return '<a class="jr-shot" href="' + esc(img(shots[k])) + '" target="_blank" rel="noopener"><img src="' + esc(img(shots[k])) + '" alt="' + esc(k) + ' screenshot" loading="lazy">' +
        esc({ highlighted: 'Highlighted (detected element)', before: 'Before interaction', after: 'After interaction', form: 'Form' }[k]) + '</a>';
    }).join('');
    return '<h4>' + esc(row.label || n.label) + '</h4><dl>' +
      '<dt>Type</dt><dd>' + chip('type', row.type_label || n.type_label) + '</dd>' +
      '<dt>Page</dt><dd>' + esc(row.page_path || n.path) + '</dd>' +
      '<dt>Status</dt><dd>' + testChip(row.test_status || n.test_status) + '</dd>' +
      '<dt>Observed</dt><dd>' + esc(row.observed || n.observed || '—') + '</dd>' +
      '<dt>Tracking</dt><dd>' + trackChip(row.tracking_status || n.tracking_status) +
        ((row.tracking_events || []).length ? '<br>' + esc(row.tracking_events.join(', ')) : '') +
        (row.tracking_note ? '<br><small>' + esc(row.tracking_note) + '</small>' : '') + '</dd>' +
      (row.destination ? '<dt>Goes to</dt><dd>' + esc(row.destination) + '</dd>' : '') +
      '<dt>Signals</dt><dd>' + esc((row.signals || []).join(' · ') || '—') + '</dd>' +
      ((n.issues || []).length ? '<dt>Issues</dt><dd>' + n.issues.map(function (i) { var f = (view.findings || [])[i]; return f ? esc(f.title) : ''; }).join('<br>') + '</dd>' : '') +
      '</dl>' + (shotHtml ? '<div class="jr-shots">' + shotHtml + '</div>' : '<p class="jr-muted">No screenshot for this element.</p>');
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

  /* ------------------------------ tables ------------------------------ */
  function renderCoverage(view) {
    var cov = (view.tracking || {}).coverage_by_type || [];
    var vendors = (view.tracking || {}).vendors || [];
    return '<p class="jr-muted">Analytics observed during the scan: ' +
      (vendors.length ? vendors.map(function (v) { return esc(v.label) + ' (' + v.hits + ' hits)'; }).join(', ') : 'none') + '.</p>' +
      table(['Interaction type', 'Tested', 'Tracked', 'Not tracked', 'Duplicate'], cov.map(function (c) {
        return [esc(c.type), c.tested, c.tracked, c.not_tracked ? '<strong style="color:var(--color-error)">' + c.not_tracked + '</strong>' : 0, c.duplicate];
      }));
  }

  function interactionRows(rows) {
    return rows.map(function (r) {
      return [esc(r.label) + '<small>' + esc(r.page_path) + '</small>', chip('type', r.type_label), testChip(r.test_status) + (r.observed ? '<small>' + esc(r.observed) + '</small>' : ''),
        trackChip(r.tracking_status) + ((r.tracking_events || []).length ? '<small>' + esc(r.tracking_events.join(', ')) + '</small>' : '')];
    });
  }

  function clickableRows(container, rows, onPick) {
    container.querySelectorAll('tr[data-index]').forEach(function (tr) {
      tr.addEventListener('click', function () { onPick(parseInt(tr.getAttribute('data-index'), 10)); });
    });
  }

  function renderGaps(view) {
    var gaps = view.gaps || [];
    if (!gaps.length) return '<p class="jr-muted">No tracking gaps among the tested conversion interactions.</p>';
    return '<p class="jr-muted">Each of these was discovered and successfully tested, but no corresponding analytics event was observed.</p>' +
      table(['Interaction', 'Type', 'Test', 'Tracking'], interactionRows(gaps), function (i) { return ' class="is-clickable" data-index="' + gaps[i].index + '"'; });
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
    return table(['Download', 'Type', 'Resource', 'Tracking'], d.map(function (x) {
      return [esc(x.label) + '<small>' + esc(x.destination) + '</small>', esc((x.file_type || '').toUpperCase() || '—'),
        x.http_status ? (x.accessible ? chip('success', 'HTTP ' + x.http_status) : chip('failed', 'HTTP ' + x.http_status)) : chip('', 'Not checked'),
        trackChip(x.tracking)];
    }), function (i) { return ' class="is-clickable" data-index="' + d[i].index + '"'; });
  }

  function renderCtas(view) {
    var c = view.ctas || [];
    return table(['CTA', 'Type', 'Test', 'Tracking'], interactionRows(c), function (i) { return ' class="is-clickable" data-index="' + c[i].index + '"'; });
  }

  function renderEvidence(view) {
    var ev = (view.evidence || []).filter(function (r) { return (r.screenshots || {}).highlighted || (r.screenshots || {}).before; });
    if (!ev.length) return '<p class="jr-muted">No screenshots captured.</p>';
    return '<div class="jr-gallery">' + ev.map(function (r) {
      var s = r.screenshots || {};
      var main = s.highlighted || s.before;
      var links = ['before', 'highlighted', 'after', 'form'].filter(function (k) { return s[k]; }).map(function (k) {
        return '<a href="' + esc(img(s[k])) + '" target="_blank" rel="noopener">' + esc(k) + '</a>';
      }).join(' · ');
      return '<div class="jr-card"><a href="' + esc(img(main)) + '" target="_blank" rel="noopener"><img src="' + esc(img(main)) + '" alt="' + esc(r.label) + '" loading="lazy"></a>' +
        '<span class="jr-card__title">#' + r.index + ' ' + esc(r.label) + '</span>' +
        '<span class="jr-card__meta">' + chip('type', r.type_label) + testChip(r.test_status) + trackChip(r.tracking_status) + '</span>' +
        '<span class="jr-muted" style="font-size:12px;">' + esc(r.page_path) + ' · ' + links + '</span></div>';
    }).join('') + '</div>';
  }

  function renderRecs(view) {
    var recs = view.recommendations || [];
    if (!recs.length) return '<p class="jr-muted">No recommendations — every tested interaction worked and was tracked.</p>';
    var sevChip = { critical: 'failed', warning: 'skipped', info: '' };
    return '<ul class="jr-recs">' + recs.map(function (r) {
      return '<li>' + chip(sevChip[r.severity], r.severity) + '<span><strong>' + esc(r.title) + '</strong><br>' + esc(r.recommendation) + '</span></li>';
    }).join('') + '</ul>';
  }

  /* ------------------------------ public ------------------------------ */
  function renderReport(journey, ids) {
    var get = function (id) { return document.getElementById(id); };
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
    get(ids.health).innerHTML = renderHealth(view);
    get(ids.summary).innerHTML = renderSummary(view);
    var mapEl = get(ids.map), detailEl = get(ids.detail);
    mapEl.innerHTML = renderMap(view);
    var firstGap = (view.gaps || [])[0];
    var firstJourney = ((view.map || {}).journeys || [])[0];
    var initial = firstGap ? nodeIdForIndex(view, firstGap.index) : (firstJourney ? firstJourney.steps[firstJourney.steps.length - 1] : null);
    detailEl.innerHTML = renderDetail(view, initial);
    wireMap(mapEl, detailEl, view);

    var pick = function (index) {
      var nid = nodeIdForIndex(view, index);
      if (!(view.map.nodes || {})[nid]) return;
      detailEl.innerHTML = renderDetail(view, nid);
      mapEl.querySelectorAll('.jr-step.is-selected').forEach(function (x) { x.classList.remove('is-selected'); });
      mapEl.querySelectorAll('[data-node="' + nid + '"]').forEach(function (x) { x.classList.add('is-selected'); });
      detailEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };
    get(ids.coverage).innerHTML = renderCoverage(view);
    get(ids.gaps).innerHTML = renderGaps(view); clickableRows(get(ids.gaps), view.gaps || [], pick);
    get(ids.forms).innerHTML = renderForms(view);
    get(ids.downloads).innerHTML = renderDownloads(view); clickableRows(get(ids.downloads), [], pick);
    get(ids.ctas).innerHTML = renderCtas(view); clickableRows(get(ids.ctas), [], pick);
    get(ids.evidence).innerHTML = renderEvidence(view);
    get(ids.recs).innerHTML = renderRecs(view);
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
    badge.textContent = gaps ? gaps + ' tracking gap' + (gaps === 1 ? '' : 's') : 'All tested steps tracked';
    var tiles = [['Interactions', c.interactions_discovered], ['Tested', c.interactions_tested], ['Tracked', c.tracked_interactions],
      ['Tracking gaps', gaps, gaps ? 'fail' : 'pass'], ['Forms', c.forms], ['Downloads', c.downloads], ['CTAs', c.ctas],
      ['Journey health', view.score == null ? '—' : view.score]];
    var nodes = (view.map || {}).nodes || {};
    var flows = ((view.map || {}).journeys || []).slice(0, 3).map(function (j) {
      return '<div class="jr-flow"><span class="jr-flow__name">' + esc(j.name) + '</span><div class="jr-flow__steps">' +
        (j.steps || []).map(function (sid, i) { return (i ? '<span class="jr-arrow">→</span>' : '') + stepButton(nodes[sid], sid); }).join('') + '</div></div>';
    }).join('');
    document.getElementById('journeyHealthBody').innerHTML =
      '<div class="jr-tiles">' + tiles.map(function (t) {
        return '<div class="jr-tile"' + (t[2] ? ' data-state="' + t[2] + '"' : '') + '><span class="jr-tile__value">' + esc(t[1] == null ? 0 : t[1]) + '</span><span class="jr-tile__label">' + esc(t[0]) + '</span></div>';
      }).join('') + '</div>' + (flows ? '<div class="jr-flows" style="margin-top:12px;">' + flows + '</div>' : '');
    document.getElementById('journeyHealthLink').href = link + '#journey';
    card.querySelectorAll('[data-node]').forEach(function (b) { b.addEventListener('click', function () { window.location.href = link + '#journey'; }); });
    card.style.display = '';
    return true;
  }

  window.JourneyRender = { renderReport: renderReport, renderDashboardCard: renderDashboardCard };
})();
