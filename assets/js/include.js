/* ==========================================================================
   include.js — OPTIONAL fetch-based loader for assets/components/*.html.
   Not loaded by any shipped page by default (see assets/components/README.md
   for why: file:// + fetch() don't mix). Add this script tag yourself if
   you're serving the site over http(s) and want live includes instead of
   copy-pasted markup.

   Usage:
     <div data-include="sidebar"></div>
     <div data-include="header"></div>
     <script src="assets/js/include.js"></script>
     <script>
       Components.includeAll().then(function () {
         document.dispatchEvent(new Event('components:ready'));
       });
     </script>
   ========================================================================== */

window.Components = window.Components || {};

(function (Components) {

  var BASE_PATH = 'assets/components/';
  var cache = {};

  function fetchComponent(name) {
    if (cache[name]) return cache[name];
    cache[name] = fetch(BASE_PATH + name + '.html')
      .then(function (res) {
        if (!res.ok) throw new Error('Failed to load component "' + name + '" (' + res.status + ')');
        return res.text();
      });
    return cache[name];
  }

  // Fetches a single component and injects it into el (innerHTML).
  function include(el) {
    var name = el.getAttribute('data-include');
    if (!name) return Promise.resolve();
    return fetchComponent(name).then(function (html) {
      el.innerHTML = html;
      // Re-execute any <script> tags in the fragment — innerHTML doesn't run them.
      el.querySelectorAll('script').forEach(function (oldScript) {
        var newScript = document.createElement('script');
        Array.prototype.forEach.call(oldScript.attributes, function (attr) {
          newScript.setAttribute(attr.name, attr.value);
        });
        newScript.textContent = oldScript.textContent;
        oldScript.parentNode.replaceChild(newScript, oldScript);
      });
    }).catch(function (err) {
      el.innerHTML = '';
      if (window.console) console.error(err);
    });
  }

  // Finds every [data-include] on the page and resolves once all are loaded.
  function includeAll(root) {
    var nodes = Array.prototype.slice.call((root || document).querySelectorAll('[data-include]'));
    return Promise.all(nodes.map(include));
  }

  Components.include = include;
  Components.includeAll = includeAll;

})(window.Components);
