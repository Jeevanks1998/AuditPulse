/* ==========================================================================
   modal.js — minimal confirm-dialog utility.
   Exposed as window.Modal.confirm({ title, body, confirmLabel, cancelLabel,
   dangerous, onConfirm, onCancel }).
   ========================================================================== */

window.Modal = (function () {

  var stylesInjected = false;

  function injectStyles() {
    if (stylesInjected) return;
    stylesInjected = true;
    var style = document.createElement('style');
    style.textContent =
      '.modal-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.5); z-index: 300; ' +
      'display: flex; align-items: center; justify-content: center; padding: 20px; animation: modalFadeIn 160ms ease both; }' +
      '.modal-dialog { background: var(--surface); border-radius: var(--radius-card); border: 1px solid var(--border); ' +
      'box-shadow: var(--shadow-lg); width: 100%; max-width: 400px; padding: var(--sp-6); animation: modalPopIn 200ms cubic-bezier(0.16,1,0.3,1) both; }' +
      '.modal-dialog__title { font-size: var(--fs-lg); font-weight: 700; color: var(--text-primary); margin-bottom: 8px; }' +
      '.modal-dialog__body { font-size: var(--fs-sm); color: var(--text-secondary); line-height: 1.5; margin-bottom: var(--sp-6); }' +
      '.modal-dialog__actions { display: flex; justify-content: flex-end; gap: 10px; }' +
      '@keyframes modalFadeIn { from { opacity: 0; } to { opacity: 1; } }' +
      '@keyframes modalPopIn { from { opacity: 0; transform: scale(0.96) translateY(6px); } to { opacity: 1; transform: scale(1) translateY(0); } }';
    document.head.appendChild(style);
  }

  function confirm(opts) {
    opts = opts || {};
    injectStyles();

    var overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML =
      '<div class="modal-dialog" role="alertdialog" aria-modal="true">' +
        '<div class="modal-dialog__title">' + window.Utils.escapeHtml(opts.title || 'Are you sure?') + '</div>' +
        '<div class="modal-dialog__body">' + window.Utils.escapeHtml(opts.body || '') + '</div>' +
        '<div class="modal-dialog__actions">' +
          '<button type="button" class="btn btn--secondary" data-action="cancel">' + window.Utils.escapeHtml(opts.cancelLabel || 'Cancel') + '</button>' +
          '<button type="button" class="btn ' + (opts.dangerous ? 'btn--danger' : 'btn--primary') + '" data-action="confirm">' + window.Utils.escapeHtml(opts.confirmLabel || 'Confirm') + '</button>' +
        '</div>' +
      '</div>';

    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';

    function close() {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      document.body.style.overflow = '';
      document.removeEventListener('keydown', onKeydown);
    }

    function onKeydown(e) {
      if (e.key === 'Escape') {
        close();
        if (opts.onCancel) opts.onCancel();
      }
    }

    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) {
        close();
        if (opts.onCancel) opts.onCancel();
      }
    });
    overlay.querySelector('[data-action="cancel"]').addEventListener('click', function () {
      close();
      if (opts.onCancel) opts.onCancel();
    });
    overlay.querySelector('[data-action="confirm"]').addEventListener('click', function () {
      close();
      if (opts.onConfirm) opts.onConfirm();
    });

    document.addEventListener('keydown', onKeydown);

    return { close: close };
  }

  return { confirm: confirm };
})();
