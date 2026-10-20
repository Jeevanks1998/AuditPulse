/* ==========================================================================
   history.js — history.html page logic. Lists the user's audits
   (window.Api.audits.getRecent()) or, in the "Deleted" view, the deleted
   audits (window.Api.history.list({ deleted: true })), rendered with
   window.Components.renderAuditRow(). Delete moves an audit to Deleted
   (soft delete, with Undo); Restore brings it back.
   ========================================================================== */

(function () {
  var U = window.Utils;

  document.addEventListener('DOMContentLoaded', function () {
    var tableBody = document.getElementById('auditTableBody');
    if (!tableBody || !window.Api || !window.Components) return; // not on history.html

    var countLabel = document.querySelector('[data-audit-table-count]');
    var deletedCount = document.querySelector('[data-deleted-count]');
    var emptyState = document.getElementById('auditTableEmpty');
    var deletedNote = document.getElementById('historyDeletedNote');
    var table = document.getElementById('auditTable');
    var searchInput = document.getElementById('historySearchInput');
    var viewButtons = U.qsa('[data-history-view]');

    var view = 'active';
    var lists = { active: [], deleted: [] };

    function loadActive() {
      return window.Api.audits.getRecent().then(function (audits) { lists.active = audits || []; });
    }

    function loadDeleted() {
      return window.Api.history.list({ deleted: true, pageSize: 100 }).then(function (page) {
        lists.deleted = (page && page.items) || [];
      });
    }

    function refresh() {
      tableBody.innerHTML = '<tr><td colspan="5" class="text-tertiary">Loading audits…</td></tr>';
      return Promise.all([loadActive(), loadDeleted().catch(function () { lists.deleted = []; })])
        .then(applyFilter)
        .catch(function () {
          tableBody.innerHTML = '';
          window.Notifications.error('Couldn\'t load audit history', 'Please refresh the page to try again.');
        });
    }

    function applyFilter() {
      if (deletedCount) deletedCount.textContent = lists.deleted.length ? '(' + lists.deleted.length + ')' : '';
      var q = searchInput ? searchInput.value.trim().toLowerCase() : '';
      var list = lists[view].filter(function (audit) {
        if (!q) return true;
        var host = U.hostnameOf(audit.url).toLowerCase();
        var label = (audit.label || '').toLowerCase();
        return host.indexOf(q) !== -1 || label.indexOf(q) !== -1;
      });
      render(list);
    }

    function setView(next) {
      view = next;
      viewButtons.forEach(function (b) {
        var on = b.dataset.historyView === view;
        b.classList.toggle('is-active', on);
        b.setAttribute('aria-selected', String(on));
      });
      if (deletedNote) deletedNote.hidden = view !== 'deleted';
      var whenHead = table && table.querySelectorAll('thead th')[3];
      if (whenHead) whenHead.textContent = view === 'deleted' ? 'Deleted' : 'Completed';
      applyFilter();
    }

    viewButtons.forEach(function (b) {
      b.addEventListener('click', function () { setView(b.dataset.historyView); });
    });
    if (searchInput) searchInput.addEventListener('input', applyFilter);

    // Delete / Restore buttons (event delegation — rows are re-rendered).
    tableBody.addEventListener('click', function (e) {
      var del = e.target.closest('[data-delete-audit]');
      var res = e.target.closest('[data-restore-audit]');
      var btn = del || res;
      if (!btn) return;
      var id = btn.getAttribute(del ? 'data-delete-audit' : 'data-restore-audit');
      var audit = lists[view].filter(function (a) { return String(a.id) === id; })[0];
      var host = audit ? U.hostnameOf(audit.url) : '';
      btn.disabled = true;
      var action = del ? window.Components.deleteAudit : window.Components.restoreAudit;
      action(id, host, refresh).catch(function () { btn.disabled = false; });
    });

    function render(list) {
      if (countLabel) {
        countLabel.textContent = list.length + (view === 'deleted' ? ' deleted' : (list.length === 1 ? ' audit' : ' audits'));
      }

      if (!list.length) {
        tableBody.innerHTML = '';
        if (table) table.style.display = 'none';
        if (emptyState) {
          var msg = emptyState.querySelector('p');
          if (msg) msg.textContent = view === 'deleted' ? 'No deleted audits.' : 'No audits match your search yet.';
          var cta = emptyState.querySelector('a');
          if (cta) cta.style.display = view === 'deleted' ? 'none' : '';
          emptyState.style.display = 'block';
        }
        return;
      }

      if (table) table.style.display = '';
      if (emptyState) emptyState.style.display = 'none';

      tableBody.innerHTML = list.map(function (audit) {
        return window.Components.renderAuditRow(audit, { deleted: view === 'deleted' });
      }).join('');
    }

    refresh();
  });
})();
