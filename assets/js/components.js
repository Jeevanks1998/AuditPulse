/* ==========================================================================
   components.js — pure-JS equivalents of a couple of components/*.html
   templates, returning HTML strings instead of requiring a fetch(). Safe to
   use from any page, including ones opened directly via file://.
   Exposed as window.Components (merges with include.js if both are loaded).
   ========================================================================== */

window.Components = window.Components || {};

(function (Components) {
  var U = window.Utils;

  // Mirrors components/score-card.html. r=26 circle → circumference ≈163.36
  function renderScoreCard(data) {
    var score = Math.max(0, Math.min(100, Number(data.score) || 0));
    var label = U.escapeHtml(data.label || '');
    var target = data.target ? ' data-target="' + U.escapeHtml(data.target) + '"' : '';
    var r = 26;
    var circumference = 2 * Math.PI * r;
    var offset = (circumference * (1 - score / 100)).toFixed(1);
    var band = U.scoreBand(score);

    return (
      '<div class="score-cell"' + target + ' role="button" tabindex="0">' +
        '<div class="vring vring--sm" data-band="' + band + '">' +
          '<svg width="64" height="64" viewBox="0 0 64 64">' +
            '<circle class="vring__track" cx="32" cy="32" r="' + r + '" stroke-width="6"/>' +
            '<circle class="vring__value" cx="32" cy="32" r="' + r + '" stroke-width="6" ' +
              'stroke-dasharray="' + circumference.toFixed(1) + '" stroke-dashoffset="' + offset + '"/>' +
          '</svg>' +
          '<div class="vring__label">' + score + '</div>' +
        '</div>' +
        '<div class="score-cell__label">' + label + '</div>' +
      '</div>'
    );
  }

  // Mirrors components/audit-table.html's row shape (a <tr> for #auditTableBody).
  function renderAuditRow(audit) {
    var band = U.scoreBand(audit.score);
    var chipClass = band === 'good' ? 'score-chip--good' : (band === 'mid' ? 'score-chip--mid' : 'score-chip--bad');
    var host = U.hostnameOf(audit.url);

    return (
      '<tr>' +
        '<td>' +
          '<div style="display:flex; align-items:center; gap:10px;">' +
            '<div class="row-item__favicon">' + U.escapeHtml(U.faviconLetter(audit.url)) + '</div>' +
            '<span>' + U.escapeHtml(host) + '</span>' +
          '</div>' +
        '</td>' +
        '<td>' + U.escapeHtml(audit.label || '') + '</td>' +
        '<td><span class="score-chip ' + chipClass + '">' + audit.score + '</span></td>' +
        '<td class="text-tertiary">' + U.escapeHtml(U.formatRelativeTime(audit.completedAt)) + '</td>' +
        '<td><a href="report.html?id=' + encodeURIComponent(audit.id) + '" class="btn btn--ghost btn--sm">View report</a></td>' +
      '</tr>'
    );
  }

  Components.renderScoreCard = renderScoreCard;
  Components.renderAuditRow = renderAuditRow;

})(window.Components);
