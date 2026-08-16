/* ==========================================================================
   internal-auth.js — internal-login.html page logic.
   Internal login: email only, no password. Entering a valid email and
   submitting signs the person straight in. The backend's /auth/login-email
   route finds-or-creates the account and writes a History row ("login"
   event) for it — once DATABASE_URL points at Supabase Postgres, that row
   lives in Supabase, so this is how "who has logged in" gets tracked there.
   ========================================================================== */

(function () {
  var U = window.Utils;
  var V = window.Validation;

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('internalLoginForm');
    if (!form) return; // not on internal-login.html

    var emailInput = document.getElementById('email');
    var emailError = document.getElementById('emailError');
    var submitBtn = document.getElementById('internalLoginSubmitBtn');

    // If already "logged in", skip straight to the dashboard.
    if (window.Api && window.Api.auth.getSession()) {
      if (location.search.indexOf('stay') === -1) {
        window.location.href = 'dashboard.html';
        return;
      }
    }

    U.on(emailInput, 'blur', function () { V.validateEmailField(emailInput, emailError); });
    U.on(emailInput, 'input', function () { V.clearFieldState(emailInput, emailError); });

    U.on(form, 'submit', function (e) {
      e.preventDefault();

      var emailOk = V.validateEmailField(emailInput, emailError);
      if (!emailOk) return;

      window.Loader.setButtonLoading(submitBtn, true, 'Signing in…');

      window.Api.auth.loginWithEmail(emailInput.value.trim())
        .then(function () {
          window.Notifications.success('Welcome', 'Redirecting to your dashboard…');
          setTimeout(function () { window.location.href = 'dashboard.html'; }, 500);
        })
        .catch(function (err) {
          window.Loader.setButtonLoading(submitBtn, false);
          window.Notifications.error('Sign in failed', err.message || 'Please check your email and try again.');
        });
    });
  });
})();
