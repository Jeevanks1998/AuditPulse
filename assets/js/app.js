/*
 * Shared app-shell behaviour on every signed-in page (and the login page):
 * mobile sidebar, theme toggle, profile menu with logout, notification bell.
 * Safe on any page: missing elements are skipped.
 */

(function () {
  var U = window.Utils;
  var CFG = window.APP_CONFIG || {};

  /* Mobile sidebar: menu button and backdrop open/close it. */
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

    // Close the drawer after a nav link is clicked.
    U.qsa('.sidebar__link', sidebar).forEach(function (link) {
      U.on(link, 'click', close);
    });
  }

  /* Theme toggle: saved in localStorage, sets [data-theme] on <html>; first visit follows the OS. */
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

  /* Profile menu: shows the signed-in user and a working Logout (also wires other Logout links). */
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

    // Also wire any other "Logout" link (e.g. the sidebar footer).
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
      // Clears the session (even if the server call fails) and goes to login.
      window.Api.auth.logout();
    } else {
      window.location.href = 'internal-login.html';
    }
  }

  /* Notification bell: lists your recently finished audits (completed or failed).
     The red dot shows when one finished since you last opened the list. */
  function initNotificationBell() {
    var actions = document.querySelector('.topbar__actions');
    if (!actions) return;
    var bell = actions.querySelector('.icon-btn[aria-label="Notifications"]');
    var user = window.Api && window.Api.auth && window.Api.auth.getUser && window.Api.auth.getUser();
    if (!bell || !user || !window.Api.history) return;

    var seenKey = 'auditpulse:notif-seen:' + (user.id || user.email || 'me');
    var dot = bell.querySelector('.dot');
    var items = [];

    var wrap = document.createElement('div');
    wrap.className = 'notif-wrap';
    bell.parentNode.insertBefore(wrap, bell);
    wrap.appendChild(bell);
    bell.setAttribute('aria-haspopup', 'true');
    bell.setAttribute('aria-expanded', 'false');

    var panel = document.createElement('div');
    panel.className = 'notif-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Notifications');
    wrap.appendChild(panel);

    function finishedAt(a) { return new Date(a.completedAt || a.createdAt).getTime() || 0; }
    function lastSeen() { return Number(U.storageGet(seenKey, 0)) || 0; }

    function updateDot() {
      var seen = lastSeen();
      var unread = items.some(function (a) { return finishedAt(a) > seen; });
      if (dot) dot.style.display = unread ? '' : 'none';
    }

    function render() {
      var seen = lastSeen();
      var html = '<div class="notif-panel__head">Notifications</div>';
      if (!items.length) {
        html += '<div class="notif-panel__empty">No finished audits yet. You\'ll see them here when they complete.</div>';
      } else {
        html += items.map(function (a) {
          var ok = a.status === 'completed';
          var site = U.escapeHtml(U.hostnameOf(a.url) || a.url);
          var text = ok
            ? 'Audit complete: <strong>' + site + '</strong>' +
              (a.overallScore != null ? ' scored <strong>' + a.overallScore + '/100</strong>' : '')
            : 'Audit failed: <strong>' + site + '</strong>';
          var href = ok ? 'report.html?id=' + encodeURIComponent(a.id) : 'history.html';
          return '<a class="notif-item' + (finishedAt(a) > seen ? ' is-unread' : '') + '" href="' + href + '">' +
            '<span class="notif-item__icon notif-item__icon--' + (ok ? 'ok' : 'fail') + '" aria-hidden="true"></span>' +
            '<span class="notif-item__body"><span class="notif-item__text">' + text + '</span>' +
            '<span class="notif-item__time">' + U.escapeHtml(U.formatRelativeTime(a.completedAt || a.createdAt)) + '</span></span>' +
          '</a>';
        }).join('');
      }
      html += '<a class="notif-panel__foot" href="history.html">View all audits</a>';
      panel.innerHTML = html;
    }

    function load() {
      return window.Api.history.list({ page: 1, pageSize: 20 }).then(function (res) {
        items = ((res && res.items) || []).filter(function (a) {
          return a.status === 'completed' || a.status === 'failed';
        }).slice(0, 8);
        updateDot();
      }).catch(function () { /* keep the bell quiet if the list can't load */ });
    }

    function close() {
      wrap.classList.remove('is-open');
      bell.setAttribute('aria-expanded', 'false');
    }

    U.on(bell, 'click', function (e) {
      e.stopPropagation();
      if (wrap.classList.contains('is-open')) { close(); return; }
      render();
      wrap.classList.add('is-open');
      bell.setAttribute('aria-expanded', 'true');
      // Opening marks everything as read (the highlight stays until the panel closes).
      U.storageSet(seenKey, String(Date.now()));
      if (dot) dot.style.display = 'none';
      load().then(function () { if (wrap.classList.contains('is-open')) render(); });
    });
    U.on(document, 'click', function (e) { if (!wrap.contains(e.target)) close(); });
    U.on(document, 'keydown', function (e) { if (e.key === 'Escape') close(); });

    if (dot) dot.style.display = 'none';
    load();
    // Check again every 2 minutes so an audit finishing in another tab shows up.
    setInterval(function () { if (!document.hidden) load(); }, 120000);
  }

  document.addEventListener('DOMContentLoaded', function () {
    initSidebar();
    initThemeToggle();
    initProfileMenu();
    initNotificationBell();
  });
})();
