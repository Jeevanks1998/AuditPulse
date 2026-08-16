/* ==========================================================================
   history.js — history.html page logic. Fetches audit rows from
   window.Api.audits.getRecent() and renders them into #auditTableBody using
   window.Components.renderAuditRow() (assets/js/components.js), matching
   the shape described in components/audit-table.html.
   ========================================================================== */

(function () {
  var U = window.Utils;

  document.addEventListener('DOMContentLoaded', function () {
    var tableBody = document.getElementById('auditTableBody');
    if (!tableBody || !window.Api || !window.Components) return; // not on history.html

    var countLabel = document.querySelector('[data-audit-table-count]');
    var emptyState = document.getElementById('auditTableEmpty');
    var table = document.getElementById('auditTable');
    var searchInput = document.getElementById('historySearchInput');

    var allAudits = [];

    tableBody.innerHTML = '<tr><td colspan="5" class="text-tertiary">Loading audits…</td></tr>';

    window.Api.audits.getRecent()
      .then(function (audits) {
        allAudits = audits || [];
        render(allAudits);
      })
      .catch(function () {
        tableBody.innerHTML = '';
        window.Notifications.error('Couldn\'t load audit history', 'Please refresh the page to try again.');
      });

    if (searchInput) {
      searchInput.addEventListener('input', function () {
        var q = searchInput.value.trim().toLowerCase();
        if (!q) {
          render(allAudits);
          return;
        }
        var filtered = allAudits.filter(function (audit) {
          var host = U.hostnameOf(audit.url).toLowerCase();
          var label = (audit.label || '').toLowerCase();
          return host.indexOf(q) !== -1 || label.indexOf(q) !== -1;
        });
        render(filtered);
      });
    }

    function render(list) {
      if (countLabel) {
        countLabel.textContent = list.length + (list.length === 1 ? ' audit' : ' audits');
      }

      if (!list.length) {
        tableBody.innerHTML = '';
        if (table) table.style.display = 'none';
        if (emptyState) emptyState.style.display = 'block';
        return;
      }

      if (table) table.style.display = '';
      if (emptyState) emptyState.style.display = 'none';

      tableBody.innerHTML = list.map(function (audit) {
        return window.Components.renderAuditRow(audit);
      }).join('');
    }
  });
})();
