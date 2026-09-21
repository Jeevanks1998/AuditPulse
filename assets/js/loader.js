/* ==========================================================================
   loader.js — button loading spinners + skeleton placeholders.
   Exposed as window.Loader.
   ========================================================================== */

window.Loader = (function () {

  var stylesInjected = false;

  function injectStyles() {
    if (stylesInjected) return;
    stylesInjected = true;
    var style = document.createElement('style');
    style.textContent =
      '.btn.is-loading { opacity: 0.85; cursor: progress; pointer-events: none; }' +
      '.btn.is-loading .spinner { border-color: rgba(255,255,255,0.35); border-top-color: #fff; }' +
      '.btn--secondary.is-loading .spinner, .btn--ghost.is-loading .spinner { border-color: var(--border); border-top-color: var(--color-primary); }' +
      '.is-skeleton { position: relative; color: transparent !important; background: linear-gradient(90deg, var(--surface-sunken) 25%, var(--border) 37%, var(--surface-sunken) 63%); ' +
      'background-size: 400% 100%; animation: skeletonShimmer 1.4s ease infinite; border-radius: 6px; user-select: none; }' +
      '@keyframes skeletonShimmer { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }';
    document.head.appendChild(style);
  }

  /* ------------------------- button loading ------------------------- */

  function setButtonLoading(btn, isLoading, loadingText) {
    if (!btn) return;
    injectStyles();

    if (isLoading) {
      if (btn.dataset.originalHtml === undefined) {
        btn.dataset.originalHtml = btn.innerHTML;
      }
      btn.disabled = true;
      btn.classList.add('is-loading');
      btn.innerHTML = '<span class="spinner"></span> ' + window.Utils.escapeHtml(loadingText || 'Loading…');
    } else {
      btn.disabled = false;
      btn.classList.remove('is-loading');
      if (btn.dataset.originalHtml !== undefined) {
        btn.innerHTML = btn.dataset.originalHtml;
        delete btn.dataset.originalHtml;
      }
    }
  }

  /* --------------------------- skeletons --------------------------- */

  function setSkeleton(el, isLoading) {
    if (!el) return;
    injectStyles();

    if (isLoading) {
      if (el.dataset.originalText === undefined) {
        el.dataset.originalText = el.textContent;
      }
      el.classList.add('is-skeleton');
      if (!el.dataset.originalMinWidth) {
        var width = Math.max(36, el.offsetWidth);
        el.style.display = 'inline-block';
        el.style.minWidth = width + 'px';
      }
    } else {
      el.classList.remove('is-skeleton');
      el.style.minWidth = '';
      if (el.dataset.originalText !== undefined) {
        delete el.dataset.originalText;
      }
    }
  }

  return {
    setButtonLoading: setButtonLoading,
    setSkeleton: setSkeleton
  };
})();
