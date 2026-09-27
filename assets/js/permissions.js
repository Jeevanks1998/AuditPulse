/* ==========================================================================
   permissions.js — Phase 4 of the AuditPulse Access Portal integration
   (see AuditPulse-Access/README.md; Phase 3 is api/access_management.py
   on the backend, which is what puts `role` and `permissions` on the
   logged-in user in the first place).

   Reads the current user's role (assets/js/api.js's Api.auth.getUser(),
   which now carries `role` and a computed `permissions` module map
   straight from the backend's UserOut — see schemas/user.py) and:
     - hides sidebar links / call-to-action buttons for modules the role
       doesn't have,
     - redirects away from a gated page reached by typing its URL
       directly, with an explanatory toast.

   This is the UX layer only. The actual enforcement is server-side
   (backend/config/permissions.py's require_module, applied to the
   scheduler/settings routers and the audit-create route) — hiding a
   button here never stops a direct API call, on purpose: a person
   editing localStorage or calling the API by hand shouldn't be able to
   grant themselves a module this file can't actually take away.
   ========================================================================== */

window.Permissions = (function () {
  var U = window.Utils;

  // Mirrors backend/config/permissions.py's MODULE_PERMISSIONS. Only used
  // as a fallback — for a session stored before this shipped, whose
  // cached user has a `role` but no `permissions` field yet. Once that
  // session refreshes (next login) the backend's own copy takes over.
  // Keep both in sync if a role's access ever changes.
  var FALLBACK_MODULE_PERMISSIONS = {
    Admin:    { dashboard: true, audits: true,  analytics: true, reports: true, scheduler: true,  settings: true },
    Auditor:  { dashboard: true, audits: true,  analytics: true, reports: true, scheduler: true,  settings: false },
    Reviewer: { dashboard: true, audits: true,  analytics: true, reports: true, scheduler: false, settings: false },
    Viewer:   { dashboard: true, audits: false, analytics: true, reports: true, scheduler: false, settings: false }
  };

  // Which page (by filename) belongs to which gated module. A page with
  // no entry here (dashboard.html, report.html, history.html) is open to
  // every role — matches the backend matrix, which has no "history" key
  // and marks dashboard/reports/analytics true for all four roles.
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

  // Whether the logged-in user's role has `module`. Modules the matrix
  // doesn't mention (e.g. "history") are treated as open to everyone,
  // and so is anything before login resolves — a missing session isn't
  // this module's problem to enforce, the page's own auth handling is.
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

  // Hides (not just disables) any link pointing at a gated page the
  // current role can't use — sidebar nav items plus any other
  // call-to-action to the same page (e.g. dashboard.html's "New Audit"
  // hero button and quick-action card). Walks every <a> on the page
  // rather than requiring a data-attribute on each one, so a future CTA
  // pointing at scheduler.html/settings.html/audit.html is covered for
  // free without needing to remember to tag it.
  function hideGatedLinks() {
    U.qsa('a[href]').forEach(function (link) {
      var module = hrefModule(link.getAttribute('href'));
      if (!module || can(module)) return;
      var item = link.closest('li') || link;
      item.style.display = 'none';
    });
  }

  // Direct-URL safety net: hiding a nav link doesn't stop someone typing
  // scheduler.html into the address bar. Bounces them to the dashboard
  // with an explanatory toast (shown there — see showDeniedNoticeIfAny)
  // rather than letting them sit on a page whose data calls are about to
  // 403 anyway. Returns true if it redirected, so init() below knows not
  // to bother running anything else on a page that's navigating away.
  function redirectIfDenied() {
    var module = PAGE_MODULES[currentPage()];
    if (!module || can(module)) return false;

    try { window.sessionStorage.setItem(DENIED_KEY, module); } catch (e) { /* ignore */ }
    window.location.replace('dashboard.html');
    return true;
  }

  // Shows the one-shot toast left behind by redirectIfDenied() once
  // landed back on an ungated page (in practice always dashboard.html,
  // its redirect target).
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

  // Small markup snippet for a "Role: X" line — app.js's initProfileMenu
  // builds the profile dropdown itself and appends this to it. This is
  // the one place Phase 4 makes the role AuditPulse read back visible to
  // the person it belongs to, rather than something only silently
  // driving what they can click.
  function roleBadgeHtml(role) {
    return '<div style="padding:2px 10px 8px; color:var(--text-tertiary); font-size:11px; ' +
      'text-transform:uppercase; letter-spacing:.04em;">Role: ' + U.escapeHtml(role || 'Viewer') + '</div>';
  }

  function init() {
    var user = window.Api && window.Api.auth.getUser();
    if (!user) return; // no session yet — nothing to gate until one exists

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
