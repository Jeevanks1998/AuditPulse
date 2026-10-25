/*
 * Protects every page except the login page. A session needs a stored token and
 * user, and the server (/auth/me) must confirm the authenticator is set up.
 * After an admin resets the authenticator, the next page load goes to login.
 */

window.AuthGuard = (function () {
  var LOGIN_PAGE = 'internal-login.html';
  var REDIRECT_KEY = 'ap_post_login_redirect';

  function currentPage() {
    return location.pathname.split('/').pop() || 'dashboard.html';
  }

  // Remember which page sent the user to login (not used yet). sessionStorage can throw, so it's guarded.
  function goToLogin() {
    try { window.sessionStorage.setItem(REDIRECT_KEY, currentPage()); } catch (e) { /* ignore */ }
    window.location.replace(LOGIN_PAGE);
  }

  // Called by api.js on any 401, so an expired session mid-visit also goes to login.
  function onUnauthorized() {
    goToLogin();
  }

  if (!window.Api || !window.Api.auth) {
    // api.js didn't load: go to login rather than show a page we can't protect.
    goToLogin();
    return { blocked: true, onUnauthorized: onUnauthorized };
  }

  function clearStoredSession() {
    try {
      var key = (window.APP_CONFIG && window.APP_CONFIG.STORAGE_KEYS && window.APP_CONFIG.STORAGE_KEYS.SESSION) || 'auditpulse:session';
      window.sessionStorage.removeItem(key);
    } catch (e) { /* ignore */ }
  }

  function authenticatorConfigured(user) {
    // Older sessions lack these fields: treat as not set up.
    return !!(user && user.mfaEnabled && !user.authSetupRequired);
  }

  var session = window.Api.auth.getSession();

  if (!session || !session.token || !session.user || !authenticatorConfigured(session.user)) {
    clearStoredSession();
    goToLogin();
    return { blocked: true, onUnauthorized: onUnauthorized };
  }

  // Check with the server in the background; only act if it fails.
  if (window.Api.auth.verifySession) {
    window.Api.auth.verifySession().then(function (user) {
      if (!authenticatorConfigured(user)) {
        clearStoredSession();
        onUnauthorized();
      }
    }).catch(onUnauthorized);
  }

  return { blocked: false, onUnauthorized: onUnauthorized };
})();
