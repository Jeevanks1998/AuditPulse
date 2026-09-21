/* ==========================================================================
   validation.js — field-level validation used by login and audit forms.
   Exposed as window.Validation.
   ========================================================================== */

window.Validation = (function () {

  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function isValidEmail(value) {
    return EMAIL_RE.test(String(value || '').trim());
  }

  function isValidUrl(value) {
    var trimmed = String(value || '').trim();
    if (!trimmed) return false;
    var withProtocol = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : 'https://' + trimmed;
    try {
      var u = new URL(withProtocol);
      if (u.protocol !== 'http:' && u.protocol !== 'https:') return false;
      // Require at least one dot in the hostname (rules out "https://localhost", "https://a")
      return /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(u.hostname);
    } catch (e) {
      return false;
    }
  }

  function toggleError(errorEl, show, message) {
    if (!errorEl) return;
    if (message != null) errorEl.textContent = message;
    errorEl.classList.toggle('is-visible', !!show);
  }

  function validateEmailField(input, errorEl) {
    if (!input) return true;
    var value = input.value.trim();
    var ok = value.length > 0 && isValidEmail(value);
    input.classList.toggle('is-invalid', !ok);
    toggleError(errorEl, !ok, value.length === 0 ? 'Email is required.' : 'Please enter a valid email address.');
    return ok;
  }

  function validatePasswordField(input, errorEl) {
    if (!input) return true;
    var value = input.value;
    var ok = value.length >= 6;
    input.classList.toggle('is-invalid', !ok);
    toggleError(errorEl, !ok, value.length === 0 ? 'Password is required.' : 'Password must be at least 6 characters.');
    return ok;
  }

  // audit.html manages the .is-invalid class on the wrapping element itself
  // (rather than the input), so this only reports validity + toggles the
  // shared error message; the caller decides what to style.
  function validateUrlField(input, errorEl) {
    if (!input) return true;
    var ok = isValidUrl(input.value);
    toggleError(errorEl, !ok);
    return ok;
  }

  function clearFieldState(el, errorEl) {
    if (el && el.classList) el.classList.remove('is-invalid');
    if (errorEl && errorEl.classList) errorEl.classList.remove('is-visible');
  }

  return {
    isValidEmail: isValidEmail,
    isValidUrl: isValidUrl,
    validateEmailField: validateEmailField,
    validatePasswordField: validatePasswordField,
    validateUrlField: validateUrlField,
    clearFieldState: clearFieldState
  };
})();
