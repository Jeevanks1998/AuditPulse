/* ==========================================================================
   internal-auth.js — internal-login.html page logic.

   Sign-in is email -> Google Authenticator (no password):

     1. Email           POST /auth/login  -> { step, challengeToken, ... }
     2a. step "setup"   first login, or the admin reset the authenticator:
                        show the QR code (+ manual key), then the code
     2b. step "verify"  authenticator already paired: just the code
     3. Code            POST /auth/verify -> session -> dashboard

   Nothing here creates an account — accounts are provisioned by an
   administrator in the Access Portal (backend/api/access_management.py).
   ========================================================================== */

(function () {
  var U = window.Utils;
  var V = window.Validation;

  document.addEventListener('DOMContentLoaded', function () {
    var emailForm = document.getElementById('internalLoginForm');
    if (!emailForm) return; // not on internal-login.html

    var emailInput = document.getElementById('email');
    var emailError = document.getElementById('emailError');
    var emailBtn = document.getElementById('internalLoginSubmitBtn');

    var setupForm = document.getElementById('setupForm');
    var setupEmail = document.getElementById('setupEmail');
    var setupQr = document.getElementById('setupQr');
    var setupSecret = document.getElementById('setupSecret');
    var setupCode = document.getElementById('setupCode');
    var setupCodeError = document.getElementById('setupCodeError');
    var setupBtn = document.getElementById('setupSubmitBtn');

    var verifyForm = document.getElementById('verifyForm');
    var verifyEmail = document.getElementById('verifyEmail');
    var verifyCode = document.getElementById('verifyCode');
    var verifyCodeError = document.getElementById('verifyCodeError');
    var verifyBtn = document.getElementById('verifySubmitBtn');

    // Short-lived token from step 1. Kept in memory only — it is not a
    // session and is never written to storage.
    var challengeToken = null;

    // If already signed in (a real session, issued only after a correct
    // authenticator code), skip straight to the dashboard.
    var existing = window.Api && window.Api.auth.getSession();
    if (existing && existing.token && existing.user) {
      if (location.search.indexOf('stay') === -1) {
        window.location.href = 'dashboard.html';
        return;
      }
    }

    function showStep(name) {
      emailForm.hidden = name !== 'email';
      setupForm.hidden = name !== 'setup';
      verifyForm.hidden = name !== 'verify';
    }

    function setFieldError(input, errorEl, message) {
      if (message) {
        input.classList.add('is-invalid');
        errorEl.textContent = message;
        errorEl.classList.add('is-visible');
      } else {
        V.clearFieldState(input, errorEl);
      }
    }

    function cleanCode(input) {
      return (input.value || '').replace(/\D/g, '').slice(0, 6);
    }

    function backToEmail() {
      challengeToken = null;
      setupCode.value = '';
      verifyCode.value = '';
      setupQr.removeAttribute('src');
      setupSecret.textContent = '';
      V.clearFieldState(setupCode, setupCodeError);
      V.clearFieldState(verifyCode, verifyCodeError);
      showStep('email');
      emailInput.focus();
    }

    // ---------------------------- step 1: email ---------------------------
    U.on(emailInput, 'blur', function () { V.validateEmailField(emailInput, emailError); });
    U.on(emailInput, 'input', function () { V.clearFieldState(emailInput, emailError); });

    U.on(emailForm, 'submit', function (e) {
      e.preventDefault();
      if (!V.validateEmailField(emailInput, emailError)) return;

      window.Loader.setButtonLoading(emailBtn, true, 'Checking…');

      window.Api.auth.login(emailInput.value.trim())
        .then(function (res) {
          window.Loader.setButtonLoading(emailBtn, false);
          challengeToken = res.challengeToken;

          if (res.step === 'setup') {
            setupEmail.textContent = res.email;
            setupQr.src = res.qrCode;
            setupSecret.textContent = (res.secret || '').replace(/(.{4})/g, '$1 ').trim();
            setupCode.value = '';
            showStep('setup');
            setupCode.focus();
          } else {
            verifyEmail.textContent = res.email;
            verifyCode.value = '';
            showStep('verify');
            verifyCode.focus();
          }
        })
        .catch(function (err) {
          window.Loader.setButtonLoading(emailBtn, false);
          window.Notifications.error('Sign in failed', err.message || 'Please check your email and try again.');
        });
    });

    // ------------------------- step 2: 6-digit code ------------------------
    function submitCode(input, errorEl, btn, isSetup) {
      var code = cleanCode(input);
      if (code.length !== 6) {
        setFieldError(input, errorEl, 'Enter the 6-digit code from Google Authenticator.');
        return;
      }
      setFieldError(input, errorEl, null);
      window.Loader.setButtonLoading(btn, true, 'Verifying…');

      window.Api.auth.verifyCode(challengeToken, code)
        .then(function () {
          window.Notifications.success(
            isSetup ? 'Authenticator set up' : 'Welcome',
            'Redirecting to your dashboard…'
          );
          setTimeout(function () { window.location.href = 'dashboard.html'; }, 500);
        })
        .catch(function (err) {
          window.Loader.setButtonLoading(btn, false);
          var msg = err.message || 'That code didn’t match. Try again.';
          // An expired/reset challenge can't be retried — start over.
          if (/enter your email again/i.test(msg)) {
            window.Notifications.error('Please sign in again', msg);
            backToEmail();
            return;
          }
          input.value = '';
          input.focus();
          setFieldError(input, errorEl, msg);
        });
    }

    [setupCode, verifyCode].forEach(function (input) {
      U.on(input, 'input', function () {
        var cleaned = cleanCode(input);
        if (input.value !== cleaned) input.value = cleaned;
        V.clearFieldState(input, input === setupCode ? setupCodeError : verifyCodeError);
      });
    });

    U.on(setupForm, 'submit', function (e) {
      e.preventDefault();
      submitCode(setupCode, setupCodeError, setupBtn, true);
    });

    U.on(verifyForm, 'submit', function (e) {
      e.preventDefault();
      submitCode(verifyCode, verifyCodeError, verifyBtn, false);
    });

    Array.prototype.forEach.call(document.querySelectorAll('[data-il-back]'), function (btn) {
      U.on(btn, 'click', backToEmail);
    });

    showStep('email');
  });
})();
