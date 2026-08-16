/* ==========================================================================
   auth.js — login.html page logic.
   Real email + password login, backed by the FastAPI /auth/login route
   (see backend/api/auth.py). On success the backend also writes a History
   row for the login event, so once DATABASE_URL points at Supabase this
   shows up in the Supabase database automatically.
   ========================================================================== */

(function () {
  var U = window.Utils;
  var V = window.Validation;

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('loginForm');
    if (!form) return; // not on login.html

    var emailInput = document.getElementById('email');
    var emailError = document.getElementById('emailError');
    var passwordInput = document.getElementById('password');
    var passwordError = document.getElementById('passwordError');
    var toggleBtn = document.getElementById('togglePassword');
    var submitBtn = document.getElementById('loginSubmitBtn');

    // If already "logged in", skip straight to the dashboard.
    if (window.Api && window.Api.auth.getSession()) {
      if (location.search.indexOf('stay') === -1) {
        window.location.href = 'dashboard.html';
        return;
      }
    }

    if (toggleBtn && passwordInput) {
      U.on(toggleBtn, 'click', function () {
        var showing = passwordInput.type === 'text';
        passwordInput.type = showing ? 'password' : 'text';
        toggleBtn.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
      });
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
          window.Notifications.success('Welcome back', 'Redirecting to your dashboard…');
          setTimeout(function () { window.location.href = 'dashboard.html'; }, 500);
        })
        .catch(function (err) {
          window.Loader.setButtonLoading(submitBtn, false);
          window.Notifications.error('Sign in failed', err.message || 'Incorrect email or password.');
        });
    });
  });
})();
