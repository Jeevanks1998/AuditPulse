/* ==========================================================================
   auth-guard.js
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

  var session = window.Api.auth.getSession();

  if (!session || !session.token) {
    goToLogin();
    return { blocked: true, onUnauthorized: onUnauthorized };
  }

  // Authoritative re-check, fired in the background: DOMContentLoaded-bound
  // code (app.js's Permissions.init(), the page's own script) doesn't wait
  // on this — it only reacts if the check comes back rejected, via the
  // same onUnauthorized() path a 401 from any other call would take.
  if (window.Api.auth.verifySession) {
    window.Api.auth.verifySession().catch(onUnauthorized);
  }

  return { blocked: false, onUnauthorized: onUnauthorized };
})();
