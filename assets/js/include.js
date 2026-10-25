/*
 * Optional loader for assets/components/*.html (not used by the shipped pages;
 * needs http(s), not file://).
 *
 *     <div data-include="sidebar"></div>
 *     <script src="assets/js/include.js"></script>
 *     <script>Components.includeAll();</script>
 */

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

  // Loads one component into el.
  function include(el) {
    var name = el.getAttribute('data-include');
    if (!name) return Promise.resolve();
    return fetchComponent(name).then(function (html) {
      el.innerHTML = html;
      // Run the fragment's <script> tags (innerHTML doesn't).
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

  // Loads every [data-include] on the page.
  function includeAll(root) {
    var nodes = Array.prototype.slice.call((root || document).querySelectorAll('[data-include]'));
    return Promise.all(nodes.map(include));
  }

  Components.include = include;
  Components.includeAll = includeAll;

})(window.Components);
