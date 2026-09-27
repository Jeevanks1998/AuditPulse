/* ==========================================================================
   app.js — shared "app shell" chrome logic, loaded on every authenticated
   page (dashboard, audit, scheduler, history, settings, report,
   email-reports) plus internal-login.html.

   RECONSTRUCTED FILE — this previously contained a near-duplicate of
   report.js's code instead of the shared chrome logic documented in
   assets/components/header.html ("Wired up by app.js: initSidebar,
   initThemeToggle, initProfileMenu, initNotificationBell"). Because of
   that, none of those four things actually did anything on any page:
     - The mobile sidebar toggle / backdrop never opened or closed.
     - The light/dark theme buttons never applied [data-theme="dark"]
       (which every other stylesheet already has rules for — see
       variables.css, HEALTH_OVERVIEW_PHASE4.css, ANALYTICS_CONSENT_PHASE5.css).
     - The profile chip in the topbar stayed stuck on the placeholder
       avatar "?" / name "…" and did nothing when clicked.
     - The sidebar's "Logout" link was a bare <a href="internal-login.html">.
       It navigated, but never called Api.auth.logout(), so the session
       was never cleared — and internal-login.html's own logic
       (assets/js/internal-auth.js) immediately bounces anyone with a
       live session straight back to dashboard.html, so "logging out"
       silently did nothing.

   Every function below is defensive about missing elements (pages differ
   in which pieces of the shell they include), so this file is safe to
   drop into any page unmodified.
   ========================================================================== */

(function () {
  var U = window.Utils;
  var CFG = window.APP_CONFIG || {};

  /* ------------------------------ sidebar (mobile) ------------------------------
     Hamburger button (#menuToggle) + backdrop (#sidebarBackdrop) toggle the
     .sidebar.is-open / .sidebar-backdrop.is-open classes responsive.css
     already defines transitions for. */
  function initSidebar() {
    var toggle = document.getElementById('menuToggle');
    var sidebar = document.getElementById('sidebar');
    var backdrop = document.getElementById('sidebarBackdrop');
    if (!toggle || !sidebar) return;

    function close() {
      sidebar.classList.remove('is-open');
      if (backdrop) backdrop.classList.remove('is-open');
      toggle.setAttribute('aria-expanded', 'false');
    }

    function open() {
      sidebar.classList.add('is-open');
      if (backdrop) backdrop.classList.add('is-open');
      toggle.setAttribute('aria-expanded', 'true');
    }

    U.on(toggle, 'click', function () {
      if (sidebar.classList.contains('is-open')) close(); else open();
    });
    U.on(backdrop, 'click', close);
    U.on(document, 'keydown', function (e) {
      if (e.key === 'Escape') close();
    });

    // A nav link click on mobile should close the drawer instead of
    // leaving it open over the page it just navigated to.
    U.qsa('.sidebar__link', sidebar).forEach(function (link) {
      U.on(link, 'click', close);
    });
  }

  /* ------------------------------ theme toggle ------------------------------
     Persists to APP_CONFIG.STORAGE_KEYS.THEME (localStorage) and sets
     [data-theme="dark"] on <html>, which every stylesheet's dark-mode rules
     already key off. Falls back to the OS preference on first visit. */
  function initThemeToggle() {
    var toggle = document.querySelector('.theme-toggle');
    if (!toggle) return;

    var lightBtn = toggle.querySelector('[aria-label="Light mode"]');
    var darkBtn = toggle.querySelector('[aria-label="Dark mode"]');
    var key = (CFG.STORAGE_KEYS && CFG.STORAGE_KEYS.THEME) || 'auditpulse:theme';

    function apply(theme) {
      if (theme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
      } else {
        document.documentElement.removeAttribute('data-theme');
      }
      if (lightBtn) lightBtn.classList.toggle('is-active', theme !== 'dark');
      if (darkBtn) darkBtn.classList.toggle('is-active', theme === 'dark');
    }

    function setTheme(theme) {
      apply(theme);
      U.storageSet(key, theme);
    }

    var stored = U.storageGet(key, null);
    var initial = stored || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    apply(initial);

    U.on(lightBtn, 'click', function () { setTheme('light'); });
    U.on(darkBtn, 'click', function () { setTheme('dark'); });
  }

  /* ------------------------------ profile menu ------------------------------
     Fills in the topbar's .profile-chip from the logged-in user
     (Api.auth.getUser()) and turns it into a dropdown with a working
     Logout item. Also wires up any other "Logout" links in the page
     (the sidebar footer link) so they clear the session properly instead
     of just navigating while still authenticated. */
  function initProfileMenu() {
    var chip = document.querySelector('.profile-chip');
    var user = window.Api && window.Api.auth.getUser();

    function initials(name, email) {
      var source = (name || email || '?').trim();
      if (!source) return '?';
      var parts = source.split(/\s+/);
      if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }

    if (chip && user) {
      var avatarEl = chip.querySelector('.profile-chip__avatar');
      var nameEl = chip.querySelector('.profile-chip__name');
      var displayName = user.name || user.fullName || user.email || 'Account';
      if (avatarEl) avatarEl.textContent = initials(user.name || user.fullName, user.email);
      if (nameEl) nameEl.textContent = displayName;
    }

    if (chip) {
      chip.setAttribute('role', 'button');
      chip.setAttribute('tabindex', '0');
      chip.setAttribute('aria-haspopup', 'true');
      chip.setAttribute('aria-expanded', 'false');
      chip.style.position = 'relative';

      var menu = document.createElement('div');
      menu.className = 'profile-menu';
      menu.setAttribute('role', 'menu');

      var roleHtml = (user && window.Permissions && window.Permissions.roleBadgeHtml)
        ? window.Permissions.roleBadgeHtml(user.role)
        : '';

      menu.innerHTML =
        roleHtml +
        '<a href="settings.html" class="profile-menu__item" role="menuitem">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>' +
          'Settings' +
        '</a>' +
        '<button type="button" class="profile-menu__item profile-menu__item--danger" role="menuitem" data-logout>' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/></svg>' +
          'Logout' +
        '</button>';

      chip.appendChild(menu);

      function closeMenu() {
        chip.classList.remove('is-open');
        chip.setAttribute('aria-expanded', 'false');
      }

      function toggleMenu(e) {
        if (e) e.stopPropagation();
        var willOpen = !chip.classList.contains('is-open');
        chip.classList.toggle('is-open', willOpen);
        chip.setAttribute('aria-expanded', String(willOpen));
      }

      U.on(chip, 'click', toggleMenu);
      U.on(chip, 'keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleMenu(); }
        if (e.key === 'Escape') closeMenu();
      });
      U.on(document, 'click', function (e) {
        if (!chip.contains(e.target)) closeMenu();
      });

      var logoutBtn = menu.querySelector('[data-logout]');
      U.on(logoutBtn, 'click', function (e) {
        e.stopPropagation();
        performLogout(logoutBtn);
      });
    }

    // Belt-and-braces: also wire up any plain "Logout" link elsewhere on
    // the page (the sidebar footer), in case it isn't inside .profile-chip.
    U.qsa('a[href="internal-login.html"]').forEach(function (link) {
      U.on(link, 'click', function (e) {
        e.preventDefault();
        performLogout(link);
      });
    });
  }

  function performLogout(triggerEl) {
    if (triggerEl) triggerEl.setAttribute('disabled', 'disabled');
    if (window.Api && window.Api.auth && window.Api.auth.logout) {
      // Api.auth.logout() clears the local session (even if the /auth/logout
      // request itself fails) and redirects to internal-login.html once done.
      window.Api.auth.logout();
    } else {
      window.location.href = 'internal-login.html';
    }
  }

  /* ------------------------------ notification bell ------------------------------
     Minimal: clears the unread dot once the person has looked at it. There's
     no notifications list/endpoint wired up yet, so this intentionally
     doesn't fabricate a dropdown full of content. */
  function initNotificationBell() {
    var actions = document.querySelector('.topbar__actions');
    if (!actions) return;
    var bell = actions.querySelector('.icon-btn[aria-label="Notifications"]');
    if (!bell) return;

    U.on(bell, 'click', function () {
      var dot = bell.querySelector('.dot');
      if (dot) dot.style.display = 'none';
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initSidebar();
    initThemeToggle();
    initProfileMenu();
    initNotificationBell();
  });
})();
