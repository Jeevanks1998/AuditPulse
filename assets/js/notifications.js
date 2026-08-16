/* ==========================================================================
   notifications.js — lightweight toast notifications.
   Exposed as window.Notifications with success/error/warning/info(title, desc).
   ========================================================================== */

window.Notifications = (function () {

  var ICONS = {
    success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m5 13 4 4L19 7"/></svg>',
    error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
    warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/></svg>'
  };

  var COLOR_VAR = {
    success: 'var(--color-success)',
    error: 'var(--color-error)',
    warning: 'var(--color-warning)',
    info: 'var(--color-primary)'
  };

  var SOFT_VAR = {
    success: 'var(--color-success-soft)',
    error: 'var(--color-error-soft)',
    warning: 'var(--color-warning-soft)',
    info: 'var(--color-primary-soft)'
  };

  var container = null;
  var stylesInjected = false;

  function injectStyles() {
    if (stylesInjected) return;
    stylesInjected = true;
    var style = document.createElement('style');
    style.textContent =
      '.toast-container { position: fixed; top: 20px; right: 20px; z-index: 200; display: flex; flex-direction: column; gap: 10px; max-width: 360px; }' +
      '.toast { display: flex; align-items: flex-start; gap: 10px; background: var(--surface); border: 1px solid var(--border); ' +
      'border-radius: var(--radius-md); box-shadow: var(--shadow-lg); padding: 12px 14px; animation: toastIn 220ms cubic-bezier(0.16,1,0.3,1) both; }' +
      '.toast.is-leaving { animation: toastOut 180ms ease both; }' +
      '.toast__icon { width: 22px; height: 22px; min-width: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }' +
      '.toast__icon svg { width: 13px; height: 13px; }' +
      '.toast__body { flex: 1; min-width: 0; }' +
      '.toast__title { font-weight: 700; font-size: var(--fs-sm); color: var(--text-primary); }' +
      '.toast__desc { font-size: 12.5px; color: var(--text-secondary); margin-top: 2px; line-height: 1.4; }' +
      '.toast__close { background: none; border: none; cursor: pointer; color: var(--text-tertiary); padding: 2px; line-height: 0; border-radius: 6px; }' +
      '.toast__close:hover { color: var(--text-primary); background: var(--surface-sunken); }' +
      '@keyframes toastIn { from { opacity: 0; transform: translateX(16px); } to { opacity: 1; transform: translateX(0); } }' +
      '@keyframes toastOut { from { opacity: 1; transform: translateX(0); } to { opacity: 0; transform: translateX(16px); } }' +
      '@media (max-width: 560px) { .toast-container { left: 12px; right: 12px; top: 12px; max-width: none; } }';
    document.head.appendChild(style);
  }

  function ensureContainer() {
    if (container && document.body.contains(container)) return container;
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
    return container;
  }

  function show(type, title, desc, duration) {
    injectStyles();
    var root = ensureContainer();

    var toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML =
      '<span class="toast__icon" style="background:' + SOFT_VAR[type] + '; color:' + COLOR_VAR[type] + ';">' + ICONS[type] + '</span>' +
      '<span class="toast__body">' +
        '<span class="toast__title">' + window.Utils.escapeHtml(title || '') + '</span>' +
        (desc ? '<span class="toast__desc">' + window.Utils.escapeHtml(desc) + '</span>' : '') +
      '</span>' +
      '<button class="toast__close" aria-label="Dismiss notification"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button>';

    root.appendChild(toast);

    var timer = setTimeout(function () { remove(toast); }, duration || 5000);

    toast.querySelector('.toast__close').addEventListener('click', function () {
      clearTimeout(timer);
      remove(toast);
    });

    function remove(el) {
      if (!el || !el.parentNode) return;
      el.classList.add('is-leaving');
      setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 200);
    }

    return toast;
  }

  return {
    success: function (title, desc, duration) { return show('success', title, desc, duration); },
    error: function (title, desc, duration) { return show('error', title, desc, duration); },
    warning: function (title, desc, duration) { return show('warning', title, desc, duration); },
    info: function (title, desc, duration) { return show('info', title, desc, duration); }
  };
})();
