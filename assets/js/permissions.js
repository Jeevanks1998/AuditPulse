/*
 * Hides links and buttons for modules the user's role can't use, and redirects
 * away from a blocked page opened by URL (with a toast).
 * Cosmetic only: the backend enforces access (config/permissions.py).
 */

window.Permissions = (function () {
  var U = window.Utils;

  // Copy of backend config/permissions.py MODULE_PERMISSIONS, used only for old sessions without `permissions`. Keep in sync.
  var FALLBACK_MODULE_PERMISSIONS = {
    Admin:    { dashboard: true, audits: true,  analytics: true, reports: true, scheduler: true,  settings: true },
    Auditor:  { dashboard: true, audits: true,  analytics: true, reports: true, scheduler: true,  settings: false },
    Reviewer: { dashboard: true, audits: true,  analytics: true, reports: true, scheduler: false, settings: false },
    Viewer:   { dashboard: true, audits: false, analytics: true, reports: true, scheduler: false, settings: false }
  };

  // Page -> module. Pages not listed are open to every role.
  var PAGE_MODULES = {
    'audit.html': 'audits',
    'scheduler.html': 'scheduler',
    'settings.html': 'settings'
  };

  var MODULE_LABELS = {
    audits: 'New Audit',
    scheduler: 'Scheduler',
    settings: 'Settings'
  };

  var DENIED_KEY = 'ap_access_denied_module';

  function currentPage() {
    return (location.pathname.split('/').pop() || 'dashboard.html');
  }

  function permissionsFor(user) {
    if (!user) return null;
    if (user.permissions) return user.permissions;
    return FALLBACK_MODULE_PERMISSIONS[user.role] || FALLBACK_MODULE_PERMISSIONS.Viewer;
  }

  // Whether the user's role has `module`. Unlisted modules, and the time before login resolves, count as allowed.
  function can(module) {
    var user = window.Api && window.Api.auth.getUser();
    var perms = permissionsFor(user);
    if (!perms) return true;
    if (!(module in perms)) return true;
    return !!perms[module];
  }

  function hrefModule(href) {
    if (!href) return null;
    var base = href.split('#')[0].split('?')[0];
    return PAGE_MODULES[base] || null;
  }

  // Hides every link to a page the role can't use (sidebar and buttons).
  function hideGatedLinks() {
    U.qsa('a[href]').forEach(function (link) {
      var module = hrefModule(link.getAttribute('href'));
      if (!module || can(module)) return;
      var item = link.closest('li') || link;
      item.style.display = 'none';
    });
  }

  // Opened by URL without access: go to the dashboard with a toast. Returns true if redirecting.
  function redirectIfDenied() {
    var module = PAGE_MODULES[currentPage()];
    if (!module || can(module)) return false;

    try { window.sessionStorage.setItem(DENIED_KEY, module); } catch (e) { /* ignore */ }
    window.location.replace('dashboard.html');
    return true;
  }

  // Shows the one-time toast left by redirectIfDenied().
  function showDeniedNoticeIfAny() {
    var module;
    try { module = window.sessionStorage.getItem(DENIED_KEY); } catch (e) { module = null; }
    if (!module) return;
    try { window.sessionStorage.removeItem(DENIED_KEY); } catch (e) { /* ignore */ }
    if (!window.Notifications) return;

    var user = window.Api && window.Api.auth.getUser();
    var role = (user && user.role) || 'your role';
    window.Notifications.warning(
      'Access restricted',
      (MODULE_LABELS[module] || module) + ' isn\u2019t available for the ' + role +
        ' role. An org admin can change this in the Access Portal.'
    );
  }

  // "Role: X" line for the profile menu.
  function roleBadgeHtml(role) {
    return '<div style="padding:2px 10px 8px; color:var(--text-tertiary); font-size:11px; ' +
      'text-transform:uppercase; letter-spacing:.04em;">Role: ' + U.escapeHtml(role || 'Viewer') + '</div>';
  }

  function init() {
    var user = window.Api && window.Api.auth.getUser();
    if (!user) return; // no session yet

    if (redirectIfDenied()) return;
    hideGatedLinks();
    showDeniedNoticeIfAny();
  }

  return {
    can: can,
    init: init,
    roleBadgeHtml: roleBadgeHtml,
    PAGE_MODULES: PAGE_MODULES
  };
})();
