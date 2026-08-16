/* ==========================================================================
   signup.js — signup.html page logic.
   Creates a real account via the FastAPI /auth/register route (see
   backend/api/auth.py -> models/user.py). The backend hashes the password,
   writes the new row to `users`, and logs a History "register" event —
   once DATABASE_URL points at Supabase Postgres both tables live there.
   ========================================================================== */

(function () {
  var U = window.Utils;
  var V = window.Validation;

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('signupForm');
    if (!form) return; // not on signup.html

    var nameInput = document.getElementById('name');
    var nameError = document.getElementById('nameError');
    var emailInput = document.getElementById('email');
    var emailError = document.getElementById('emailError');
    var companyInput = document.getElementById('company');
    var passwordInput = document.getElementById('password');
    var passwordError = document.getElementById('passwordError');
    var confirmInput = document.getElementById('confirmPassword');
    var confirmError = document.getElementById('confirmPasswordError');
    var toggleBtn = document.getElementById('togglePassword');
    var submitBtn = document.getElementById('signupSubmitBtn');

    // Already signed in? No need to sign up again.
    if (window.Api && window.Api.auth.getSession()) {
      window.location.href = 'dashboard.html';
      return;
    }

    if (toggleBtn && passwordInput) {
      U.on(toggleBtn, 'click', function () {
        var showing = passwordInput.type === 'text';
        passwordInput.type = showing ? 'password' : 'text';
        toggleBtn.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
      });
    }

    function validateName() {
      var ok = nameInput.value.trim().length > 0;
      nameInput.classList.toggle('is-invalid', !ok);
      nameError.textContent = 'Please enter your name.';
      nameError.classList.toggle('is-visible', !ok);
      return ok;
    }

    function validateConfirm() {
      var ok = confirmInput.value.length > 0 && confirmInput.value === passwordInput.value;
      confirmInput.classList.toggle('is-invalid', !ok);
      confirmError.textContent = confirmInput.value.length === 0
        ? 'Please confirm your password.'
        : 'Passwords do not match.';
      confirmError.classList.toggle('is-visible', !ok);
      return ok;
    }

    U.on(nameInput, 'blur', validateName);
    U.on(nameInput, 'input', function () { V.clearFieldState(nameInput, nameError); });
    U.on(emailInput, 'blur', function () { V.validateEmailField(emailInput, emailError); });
    U.on(emailInput, 'input', function () { V.clearFieldState(emailInput, emailError); });
    U.on(passwordInput, 'blur', function () { V.validatePasswordField(passwordInput, passwordError); });
    U.on(passwordInput, 'input', function () { V.clearFieldState(passwordInput, passwordError); });
    U.on(confirmInput, 'blur', validateConfirm);
    U.on(confirmInput, 'input', function () { V.clearFieldState(confirmInput, confirmError); });

    U.on(form, 'submit', function (e) {
      e.preventDefault();

      var nameOk = validateName();
      var emailOk = V.validateEmailField(emailInput, emailError);
      var passwordOk = V.validatePasswordField(passwordInput, passwordError);
      var confirmOk = validateConfirm();
      if (!nameOk || !emailOk || !passwordOk || !confirmOk) return;

      window.Loader.setButtonLoading(submitBtn, true, 'Creating account…');

      window.Api.auth.register(
        nameInput.value.trim(),
        emailInput.value.trim(),
        passwordInput.value,
        companyInput.value.trim()
      )
        .then(function () {
          window.Notifications.success('Account created', 'Redirecting to your dashboard…');
          setTimeout(function () { window.location.href = 'dashboard.html'; }, 500);
        })
        .catch(function (err) {
          window.Loader.setButtonLoading(submitBtn, false);
          window.Notifications.error('Sign up failed', err.message || 'Please check your details and try again.');
        });
    });
  });
})();
