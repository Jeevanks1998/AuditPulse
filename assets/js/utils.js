/* ==========================================================================
   utils.js — small, dependency-free helpers reused across every page script.
   Exposed as window.Utils.
   ========================================================================== */

window.Utils = (function () {

  /* ------------------------------ DOM ------------------------------ */

  function qs(selector, root) {
    return (root || document).querySelector(selector);
  }

  function qsa(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function on(el, event, handler) {
    if (!el) return;
    el.addEventListener(event, handler);
  }

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /* --------------------------- formatting --------------------------- */

  function hostnameOf(url) {
    if (!url) return '';
    var value = String(url).trim();
    try {
      var withProtocol = /^[a-z][a-z0-9+.-]*:\/\//i.test(value) ? value : 'https://' + value;
      var host = new URL(withProtocol).hostname;
      return host.replace(/^www\./i, '');
    } catch (e) {
      return value.replace(/^www\./i, '');
    }
  }

  function faviconLetter(url) {
    var host = hostnameOf(url);
    return host ? host.charAt(0).toUpperCase() : '?';
  }

  function scoreBand(score) {
    var bands = (window.APP_CONFIG && window.APP_CONFIG.SCORE_BANDS) || { good: 80, mid: 50 };
    var n = Number(score);
    if (n >= bands.good) return 'good';
    if (n >= bands.mid) return 'mid';
    return 'bad';
  }

  function formatRelativeTime(input) {
    if (input == null) return '';
    var then = (input instanceof Date) ? input.getTime() : new Date(input).getTime();
    if (isNaN(then)) return String(input);

    var diffMs = Date.now() - then;
    var diffSec = Math.round(diffMs / 1000);

    if (diffSec < 45) return 'Just now';
    var diffMin = Math.round(diffSec / 60);
    if (diffMin < 60) return diffMin + (diffMin === 1 ? ' min ago' : ' min ago');
    var diffHr = Math.round(diffMin / 60);
    if (diffHr < 24) return diffHr === 1 ? '1 hour ago' : diffHr + ' hours ago';
    var diffDay = Math.round(diffHr / 24);
    if (diffDay === 1) return 'Yesterday';
    if (diffDay < 7) return diffDay + ' days ago';

    var d = new Date(then);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }

  /* ------------------------------ rings ------------------------------ */

  function setRingProgress(circleEl, percent) {
    if (!circleEl) return;
    var r = parseFloat(circleEl.getAttribute('r')) || 38;
    var circumference = 2 * Math.PI * r;
    var clamped = Math.max(0, Math.min(100, Number(percent) || 0));
    var offset = circumference * (1 - clamped / 100);
    circleEl.style.strokeDasharray = circumference.toFixed(2);
    circleEl.style.strokeDashoffset = offset.toFixed(2);
  }

  function setRingBand(ringEl, score) {
    if (!ringEl) return;
    ringEl.setAttribute('data-band', scoreBand(score));
  }

  /* ---------------------------- animation ---------------------------- */

  function animateCountUp(el, target, duration, suffix) {
    if (!el) return;
    suffix = suffix || '';
    var targetNum = Number(target) || 0;
    var startNum = parseFloat(el.textContent) || 0;
    var startTime = null;
    duration = duration || 600;

    function tick(ts) {
      if (startTime === null) startTime = ts;
      var progress = Math.min(1, (ts - startTime) / duration);
      var eased = 1 - Math.pow(1 - progress, 3);
      var current = Math.round(startNum + (targetNum - startNum) * eased);
      el.textContent = current + suffix;
      if (progress < 1) {
        window.requestAnimationFrame(tick);
      } else {
        el.textContent = targetNum + suffix;
      }
    }
    window.requestAnimationFrame(tick);
  }

  /* ----------------------------- storage ----------------------------- */

  function storageGet(key, fallback) {
    try {
      var v = window.localStorage.getItem(key);
      return v === null ? fallback : v;
    } catch (e) {
      return fallback;
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
      return true;
    } catch (e) {
      return false;
    }
  }

  function storageGetJSON(key, fallback) {
    try {
      var raw = window.localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  }

  function storageSetJSON(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (e) {
      return false;
    }
  }

  function storageRemove(key) {
    try {
      window.localStorage.removeItem(key);
      return true;
    } catch (e) {
      return false;
    }
  }

  /* ---------------------------- clipboard ---------------------------- */

  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        resolve();
      } catch (err) {
        reject(err);
      }
    });
  }

  function downloadTextFile(filename, content, mime) {
    var blob = new Blob([content], { type: mime || 'text/plain' });
    downloadBlob(filename, blob);
  }

  // Same trigger-a-download dance as downloadTextFile, but for a Blob we
  // already have (e.g. a PDF fetched as a binary response) rather than text
  // we need to wrap in one ourselves.
  function downloadBlob(filename, blob) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  // Reads a single query-string parameter from the current page URL, e.g.
  // getQueryParam('id') on "report.html?id=42" -> "42". Returns null if
  // the param isn't present.
  function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  return {
    qs: qs,
    qsa: qsa,
    on: on,
    escapeHtml: escapeHtml,
    hostnameOf: hostnameOf,
    faviconLetter: faviconLetter,
    scoreBand: scoreBand,
    formatRelativeTime: formatRelativeTime,
    setRingProgress: setRingProgress,
    setRingBand: setRingBand,
    animateCountUp: animateCountUp,
    storageGet: storageGet,
    storageSet: storageSet,
    storageGetJSON: storageGetJSON,
    storageSetJSON: storageSetJSON,
    storageRemove: storageRemove,
    copyToClipboard: copyToClipboard,
    downloadTextFile: downloadTextFile,
    downloadBlob: downloadBlob,
    getQueryParam: getQueryParam
  };
})();
