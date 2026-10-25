/* HTML-string versions of some components/*.html templates (no fetch needed). Exposed as window.Components. */

window.Components = window.Components || {};

(function (Components) {
  var U = window.Utils;

  // Same as components/score-card.html. r=26 -> circumference ~163.36
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

  var ICON_TRASH = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/></svg>';
  var ICON_RESTORE = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>';

  // One audit table row. opts.deleted: show Restore instead of Delete.
  function renderAuditRow(audit, opts) {
    opts = opts || {};
    var host = U.hostnameOf(audit.url);

    // Only finished audits have a score; others show a dash, Failed or Running.
    var isCompleted = audit.status === 'completed';
    var hasScore = isCompleted && audit.overallScore !== null && audit.overallScore !== undefined
      && !isNaN(Number(audit.overallScore));
    var scoreCell;
    if (hasScore) {
      var band = U.scoreBand(audit.overallScore);
      var chipClass = band === 'good' ? 'score-chip--good' : (band === 'mid' ? 'score-chip--mid' : 'score-chip--bad');
      scoreCell = '<span class="score-chip ' + chipClass + '">' + audit.overallScore + '</span>';
    } else {
      scoreCell = '<span class="score-chip score-chip--neutral">' + (audit.status === 'failed' ? 'Failed' : audit.status === 'running' ? 'Running…' : isCompleted ? 'Not scored' : '–') + '</span>';
    }

    var whenLabel = opts.deleted
      ? (audit.deletedAt ? 'Deleted ' + U.formatRelativeTime(audit.deletedAt) : 'Deleted')
      : (audit.completedAt ? U.formatRelativeTime(audit.completedAt) : '—');
    var busy = audit.status === 'running' || audit.status === 'queued';

    var actions = (isCompleted
      ? '<a href="report.html?id=' + encodeURIComponent(audit.id) + '" class="btn btn--ghost btn--sm">View report</a>'
      : '<span class="text-tertiary" style="font-size:13px;">Not available</span>');
    if (opts.deleted) {
      actions += '<button type="button" class="btn btn--ghost btn--sm audit-action" data-restore-audit="' + U.escapeHtml(String(audit.id)) + '" title="Restore this audit">' + ICON_RESTORE + '<span>Restore</span></button>';
    } else if (!busy) {
      actions += '<button type="button" class="btn btn--ghost btn--sm audit-action audit-action--danger" data-delete-audit="' + U.escapeHtml(String(audit.id)) + '" title="Delete this audit (you can restore it later)" aria-label="Delete audit of ' + U.escapeHtml(host) + '">' + ICON_TRASH + '<span>Delete</span></button>';
    }

    return (
      '<tr data-audit-row="' + U.escapeHtml(String(audit.id)) + '">' +
        '<td>' +
          '<div style="display:flex; align-items:center; gap:10px;">' +
            '<div class="row-item__favicon">' + U.escapeHtml(U.faviconLetter(audit.url)) + '</div>' +
            '<span>' + U.escapeHtml(host) + '</span>' +
          '</div>' +
        '</td>' +
        '<td>' + U.escapeHtml(audit.label || '') + '</td>' +
        '<td>' + scoreCell + '</td>' +
        '<td class="text-tertiary">' + U.escapeHtml(whenLabel) + '</td>' +
        '<td><div class="audit-actions">' + actions + '</div></td>' +
      '</tr>'
    );
  }

  /* Deletes an audit (soft) with Undo in the toast; onChange() runs after delete and undo. */
  function deleteAudit(auditId, host, onChange) {
    if (window.Modal && window.Modal.confirm) {
      return new Promise(function (resolve, reject) {
        window.Modal.confirm({
          title: 'Delete this audit?',
          body: (host ? host + ' — ' : '') + 'it will be moved to Deleted audits with its full report. You can restore it from Audit history at any time.',
          confirmLabel: 'Delete',
          cancelLabel: 'Cancel',
          dangerous: true,
          onConfirm: function () { doDelete(auditId, host, onChange).then(resolve, reject); },
          onCancel: function () { reject(new Error('cancelled')); }
        });
      });
    }
    return doDelete(auditId, host, onChange);
  }

  function doDelete(auditId, host, onChange) {
    return window.Api.history.remove(auditId).then(function () {
      if (onChange) onChange();
      var toast = window.Notifications.success('Audit deleted',
        (host ? host + ' was moved to Deleted audits. ' : 'Moved to Deleted audits. ') + 'You can restore it from Audit history.', 8000);
      var body = toast && toast.querySelector('.toast__body');
      if (body) {
        var undo = document.createElement('button');
        undo.type = 'button';
        undo.className = 'btn btn--ghost btn--sm';
        undo.style.cssText = 'margin-top:6px;align-self:flex-start;';
        undo.textContent = 'Undo';
        undo.addEventListener('click', function () {
          undo.disabled = true;
          restoreAudit(auditId, host, onChange);
          if (toast.parentNode) toast.parentNode.removeChild(toast);
        });
        body.appendChild(undo);
      }
    }).catch(function (err) {
      window.Notifications.error('Couldn\'t delete the audit', (err && err.message) || 'Please try again.');
      throw err;
    });
  }

  function restoreAudit(auditId, host, onChange) {
    return window.Api.history.restore(auditId).then(function () {
      window.Notifications.success('Audit restored', (host ? host + ' is' : 'It is') + ' back in Audit history and Recent Audits.');
      if (onChange) onChange();
    }).catch(function (err) {
      window.Notifications.error('Couldn\'t restore the audit', (err && err.message) || 'Please try again.');
      throw err;
    });
  }

  Components.renderScoreCard = renderScoreCard;
  Components.renderAuditRow = renderAuditRow;
  Components.deleteAudit = deleteAudit;
  Components.restoreAudit = restoreAudit;

})(window.Components);
