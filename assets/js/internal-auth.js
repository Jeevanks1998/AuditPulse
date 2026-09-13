/* ==========================================================================
   internal-auth.js — internal-login.html page logic.
   Internal login: email + password, checked against an account an
   administrator has already created and activated (see
   backend/api/access_management.py). Nothing here creates an account —
   the backend's /auth/login route just verifies credentials and rejects
   inactive accounts.
   ========================================================================== */

(function () {
  var U = window.Utils;
  var V = window.Validation;

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('internalLoginForm');
    if (!form) return; // not on internal-login.html

    var emailInput = document.getElementById('email');
    var emailError = document.getElementById('emailError');
    var passwordInput = document.getElementById('password');
    var passwordError = document.getElementById('passwordError');
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
    U.on(passwordInput, 'blur', function () { V.validatePasswordField(passwordInput, passwordError); });
    U.on(passwordInput, 'input', function () { V.clearFieldState(passwordInput, passwordError); });

    U.on(form, 'submit', function (e) {
      e.preventDefault();

      var emailOk = V.validateEmailField(emailInput, emailError);
      var passwordOk = V.validatePasswordField(passwordInput, passwordError);
      if (!emailOk || !passwordOk) return;

      window.Loader.setButtonLoading(submitBtn, true, 'Signing in…');

      window.Api.auth.login(emailInput.value.trim(), passwordInput.value)
        .then(function () {
          window.Notifications.success('Welcome', 'Redirecting to your dashboard…');
          setTimeout(function () { window.location.href = 'dashboard.html'; }, 500);
        })
        .catch(function (err) {
          window.Loader.setButtonLoading(submitBtn, false);
          window.Notifications.error('Sign in failed', err.message || 'Please check your email and password and try again.');
        });
    });
  });
})();
