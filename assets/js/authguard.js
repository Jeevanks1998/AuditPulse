/* ==========================================================================
   auth-guard.js

   Protects every page except internal-login.html. A valid session only
   exists after the full email -> Google Authenticator sign-in: the
   backend issues the session token from /auth/verify, never from the
   email step (that returns a short-lived challenge token that is never
   stored). So the guard checks:

     1. there is a stored session with a token and a user, and
     2. the server confirms it (/auth/me) and reports the authenticator
        as configured (mfaEnabled && !authSetupRequired).

   If an admin resets the person's authenticator in the Access Portal,
   check 2 fails on their next page load and they are sent back to login
   to scan a new QR code.
   ========================================================================== */

window.AuthGuard = (function () {
  var LOGIN_PAGE = 'internal-login.html';
  var REDIRECT_KEY = 'ap_post_login_redirect';

  function currentPage() {
    return location.pathname.split('/').pop() || 'dashboard.html';
  }

  // Remembers which page sent the person to login, purely so a future
  // "redirect back after sign-in" feature has somewhere to read from —
  // internal-auth.js doesn't consume this yet, so today it's a no-op
  // beyond the sessionStorage write. Wrapped in try/catch since
  // sessionStorage can throw in locked-down/private-browsing contexts,
  // and a storage failure should never block the redirect itself.
  function goToLogin() {
    try { window.sessionStorage.setItem(REDIRECT_KEY, currentPage()); } catch (e) { /* ignore */ }
    window.location.replace(LOGIN_PAGE);
  }

  // Called by api.js's request() helper whenever any authenticated call —
  // not just this file's own verifySession() — comes back 401. Centralizing
  // it here means a token that expires *mid-session* (not just a missing
  // session at page load) also bounces the person back to login, using the
  // exact same path as every other case, rather than leaving them stuck on
  // a page silently failing every data call.
  function onUnauthorized() {
    goToLogin();
  }

  if (!window.Api || !window.Api.auth) {
    // api.js didn't load (network/CDN issue, wrong script order, etc.) —
    // fail safe by sending the person to login rather than silently
    // rendering a protected page with no way to verify who they are.
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
    // Older sessions (from before the authenticator change) carry a user
    // object without these fields — treat that as "not configured".
    return !!(user && user.mfaEnabled && !user.authSetupRequired);
  }

  var session = window.Api.auth.getSession();

  if (!session || !session.token || !session.user || !authenticatorConfigured(session.user)) {
    clearStoredSession();
    goToLogin();
    return { blocked: true, onUnauthorized: onUnauthorized };
  }

  // Authoritative re-check, fired in the background: DOMContentLoaded-bound
  // code (app.js's Permissions.init(), the page's own script) doesn't wait
  // on this — it only reacts if the check comes back rejected, via the
  // same onUnauthorized() path a 401 from any other call would take.
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
