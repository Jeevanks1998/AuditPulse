/* ==========================================================================
   score-help.js — "How is this scored?" explainer.
   window.ScoreHelp.open(scoreGrid?, overall?) opens a dialog that explains
   what the 0-100 scores mean, how each module's score is built, and (when
   an audit's score grid is passed) the actual overall calculation for that
   audit. window.ScoreHelp.link(label?) returns the button HTML.

   The numbers here mirror the backend so the explanation never drifts:
     * config/constants.py MODULE_WEIGHTS          (overall weighting)
     * consent/consent_score.py CATEGORY_WEIGHTS    (consent areas)
     * analytics/analytics_score.py CATEGORY_WEIGHTS (analytics areas)
     * *_score.py SEVERITY_PENALTY                  (points per issue)
     * journey/journey_qa.py compute_health         (journey formula)
     * reports/generator.py score bands             (80 / 50)
   ========================================================================== */

window.ScoreHelp = (function () {

  var MODULE_WEIGHTS = { consent: 20, analytics: 15, journey: 15 };
  var DEFAULT_WEIGHT = 5;
  var MODULE_NAMES = { consent: 'Consent', analytics: 'Analytics', journey: 'Journey Map', cookies: 'Cookie Scanner' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function bands() {
    return (window.APP_CONFIG && window.APP_CONFIG.SCORE_BANDS) || { good: 80, mid: 50 };
  }

  function bandLabel(score) {
    if (score == null || isNaN(Number(score))) return '';
    var b = bands(), n = Number(score);
    return n >= b.good ? 'Healthy' : (n >= b.mid ? 'Needs attention' : 'Issues found');
  }

  var stylesInjected = false;
  function injectStyles() {
    if (stylesInjected) return;
    stylesInjected = true;
    var css =
      '.score-help-link{display:inline-flex;align-items:center;gap:5px;background:none;border:0;padding:2px 0;cursor:pointer;' +
      'font:inherit;font-size:var(--fs-xs,12px);font-weight:600;color:var(--color-primary,#4F46E5);}' +
      '.score-help-link:hover{text-decoration:underline;}' +
      '.score-help-link svg{width:14px;height:14px;flex:none;}' +
      '.sh-overlay{position:fixed;inset:0;background:rgba(15,23,42,.5);z-index:400;display:flex;align-items:center;justify-content:center;padding:16px;}' +
      '.sh-dialog{background:var(--surface,#fff);color:var(--text-primary,#0f172a);border:1px solid var(--border,#e2e8f0);border-radius:var(--radius-card,14px);' +
      'box-shadow:var(--shadow-lg,0 20px 40px rgba(0,0,0,.2));width:100%;max-width:640px;max-height:calc(100vh - 32px);display:flex;flex-direction:column;}' +
      '.sh-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 22px;border-bottom:1px solid var(--border,#e2e8f0);}' +
      '.sh-head h2{font-size:var(--fs-lg,18px);font-weight:700;margin:0;}' +
      '.sh-close{background:none;border:0;cursor:pointer;font-size:22px;line-height:1;color:var(--text-tertiary,#64748b);padding:4px 8px;border-radius:8px;}' +
      '.sh-close:hover{background:var(--surface-sunken,#f1f5f9);}' +
      '.sh-body{padding:18px 22px 22px;overflow:auto;font-size:var(--fs-sm,14px);line-height:1.6;color:var(--text-secondary,#334155);}' +
      '.sh-body h3{font-size:var(--fs-sm,14px);font-weight:700;color:var(--text-primary,#0f172a);margin:18px 0 6px;}' +
      '.sh-body p{margin:0 0 8px;}' +
      '.sh-body ul{margin:4px 0 8px;padding-left:18px;}' +
      '.sh-body li{margin:2px 0;}' +
      '.sh-bands{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:8px 0 4px;}' +
      '.sh-band{border-radius:10px;padding:8px 10px;font-size:var(--fs-xs,12px);}' +
      '.sh-band strong{display:block;font-size:var(--fs-sm,14px);}' +
      '.sh-band--good{background:var(--color-success-soft,#dcfce7);color:var(--color-success,#15803d);}' +
      '.sh-band--mid{background:var(--color-warning-soft,#fef3c7);color:#B45309;}' +
      '.sh-band--bad{background:var(--color-error-soft,#fee2e2);color:var(--color-error,#b91c1c);}' +
      '.sh-calc{background:var(--surface-sunken,#f1f5f9);border-radius:10px;padding:10px 12px;font-family:var(--font-mono,monospace);' +
      'font-size:var(--fs-xs,12px);color:var(--text-primary,#0f172a);overflow-x:auto;}' +
      '.sh-pen{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 8px;}' +
      '.sh-pen span{font-size:var(--fs-xs,12px);font-weight:600;padding:2px 8px;border-radius:999px;}' +
      '.sh-pen .c{background:var(--color-error-soft,#fee2e2);color:var(--color-error,#b91c1c);}' +
      '.sh-pen .w{background:var(--color-warning-soft,#fef3c7);color:#B45309;}' +
      '.sh-pen .i{background:var(--surface-sunken,#f1f5f9);color:var(--text-secondary,#334155);}' +
      '.sh-body details{border:1px solid var(--border,#e2e8f0);border-radius:10px;padding:8px 12px;margin:8px 0;}' +
      '.sh-body summary{cursor:pointer;font-weight:700;color:var(--text-primary,#0f172a);}' +
      '.sh-body details[open] summary{margin-bottom:6px;}' +
      '.sh-note{font-size:var(--fs-xs,12px);color:var(--text-tertiary,#64748b);}' +
      '@media (max-width:560px){.sh-bands{grid-template-columns:1fr;}.sh-head,.sh-body{padding-left:16px;padding-right:16px;}}';
    var style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
  }

  var ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>';

  function link(label) {
    injectStyles();
    return '<button type="button" class="score-help-link" data-score-help>' + ICON + esc(label || 'How is this scored?') + '</button>';
  }

  function calcHtml(scoreGrid, overall) {
    var cells = (scoreGrid || []).filter(function (c) { return c && c.score != null; });
    if (!cells.length) return '';
    var html = '<h3>This audit’s overall score</h3>';
    if (cells.length === 1) {
      return html + '<p>Only ' + esc(cells[0].label || MODULE_NAMES[cells[0].module] || cells[0].module) +
        ' was scored, so the overall score is that module’s score: <strong>' + esc(cells[0].score) + '/100</strong>.</p>';
    }
    var parts = [], sum = 0, total = 0;
    cells.forEach(function (c) {
      var w = MODULE_WEIGHTS[c.module] != null ? MODULE_WEIGHTS[c.module] : DEFAULT_WEIGHT;
      parts.push(esc(c.label || MODULE_NAMES[c.module] || c.module) + ' ' + esc(c.score) + ' × ' + w);
      sum += Number(c.score) * w;
      total += w;
    });
    var result = overall != null ? overall : Math.round(sum / total);
    return html +
      '<p>A weighted average of the modules that ran. Consent counts a little more because it is checked with a real browser and carries legal risk.</p>' +
      '<div class="sh-calc">(' + parts.join(' + ') + ') ÷ ' + total + ' = <strong>' + esc(result) + '/100</strong></div>';
  }

  function bodyHtml(scoreGrid, overall) {
    var b = bands();
    return '' +
      '<p><strong>Every score is a health rating out of 100, not a percentage.</strong> 100 means no problems were found. ' +
      'Points are taken off for each problem, and more for serious ones. So 77 does not mean “77% compliant” or “77% of checks passed”; ' +
      'it means the module lost 23 points because of the issues listed in the report.</p>' +
      '<div class="sh-bands">' +
        '<div class="sh-band sh-band--good"><strong>' + b.good + '–100</strong>Healthy</div>' +
        '<div class="sh-band sh-band--mid"><strong>' + b.mid + '–' + (b.good - 1) + '</strong>Needs attention</div>' +
        '<div class="sh-band sh-band--bad"><strong>0–' + (b.mid - 1) + '</strong>Issues found</div>' +
      '</div>' +
      calcHtml(scoreGrid, overall) +
      '<h3>How Consent and Analytics are scored</h3>' +
      '<p>Each module is split into areas. Every area starts at 100 and loses points for each issue found in it (never below 0):</p>' +
      '<div class="sh-pen"><span class="c">Critical −30</span><span class="w">Warning −15</span><span class="i">Info −5</span></div>' +
      '<p>The module score is the weighted average of its areas, so the areas that matter most count most.</p>' +
      '<details><summary>Consent areas and weights</summary><ul>' +
        '<li>Cookie banner is present: 25</li>' +
        '<li>Tracking is really held back until consent: 20</li>' +
        '<li>Live click test (Accept / Reject in a real browser): 20</li>' +
        '<li>Accept / Reject / Settings buttons: 15</li>' +
        '<li>Cookies set before consent: 15</li>' +
        '<li>Network requests before consent: 10</li>' +
        '<li>Preference centre / changing your choice later: 10</li>' +
        '<li>Google Consent Mode: 5</li>' +
      '</ul><p class="sh-note">Weights are relative (they are divided by their total).</p></details>' +
      '<details><summary>Analytics areas and weights</summary><ul>' +
        '<li>Google Analytics 4: 15</li>' +
        '<li>Google Tag Manager: 15</li>' +
        '<li>Data layer: 15</li>' +
        '<li>Adobe Analytics: 10</li>' +
        '<li>Meta Pixel: 10</li>' +
        '<li>Duplicate tags: 10</li>' +
        '<li>Piano, Microsoft Clarity, Hotjar, LinkedIn, TikTok and other tags: 5 each</li>' +
      '</ul><p class="sh-note">A tool that isn’t on the site has no issues, so its area stays at 100.</p></details>' +
      '<h3>How the Journey Map is scored</h3>' +
      '<p>Journey Health is built from what happened when AuditPulse safely clicked the site’s buttons, links and forms:</p>' +
      '<ul>' +
        '<li><strong>45%</strong>: conversion clicks and forms that were picked up by analytics</li>' +
        '<li><strong>35%</strong>: interactions that worked when clicked</li>' +
        '<li><strong>20%</strong>: interactions with screenshot evidence captured</li>' +
      '</ul>' +
      '<p class="sh-note">If no interaction could be tested, the Journey Map shows “Not scored” instead of 0.</p>' +
      '<h3>Cookie Scanner</h3>' +
      '<p>The Cookie Scanner has no score of its own. It is a full list of the cookies found, with their category, lifetime and party. ' +
      'Cookies set before consent already lower the Consent score.</p>' +
      '<h3>Issue counts</h3>' +
      '<p>The Critical / Warnings / Info boxes count distinct issues. The same problem on many pages counts once.</p>';
  }

  var openOverlay = null;

  function close() {
    if (!openOverlay) return;
    openOverlay.remove();
    openOverlay = null;
    document.removeEventListener('keydown', onKey);
  }

  function onKey(e) { if (e.key === 'Escape') close(); }

  function open(scoreGrid, overall) {
    injectStyles();
    close();
    var overlay = document.createElement('div');
    overlay.className = 'sh-overlay';
    overlay.innerHTML =
      '<div class="sh-dialog" role="dialog" aria-modal="true" aria-labelledby="shTitle">' +
        '<div class="sh-head"><h2 id="shTitle">How the scores work</h2>' +
        '<button type="button" class="sh-close" aria-label="Close">×</button></div>' +
        '<div class="sh-body">' + bodyHtml(scoreGrid, overall) + '</div>' +
      '</div>';
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay || e.target.closest('.sh-close')) close();
    });
    document.body.appendChild(overlay);
    document.addEventListener('keydown', onKey);
    openOverlay = overlay;
    var btn = overlay.querySelector('.sh-close');
    if (btn) btn.focus();
  }

  // Any [data-score-help] button on the page opens the explainer with the
  // score grid the page registered via setContext (report page), or the
  // general explanation when there is none (dashboard).
  var ctx = { grid: null, overall: null };
  function setContext(scoreGrid, overall) { ctx.grid = scoreGrid || null; ctx.overall = overall == null ? null : overall; }
  document.addEventListener('click', function (e) {
    var t = e.target && e.target.closest ? e.target.closest('[data-score-help]') : null;
    if (!t) return;
    e.preventDefault();
    e.stopPropagation();
    open(ctx.grid, ctx.overall);
  });
  injectStyles();

  return { open: open, link: link, bandLabel: bandLabel, close: close, setContext: setContext };
})();
