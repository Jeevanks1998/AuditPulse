# assets/components/

Reference/reuse templates for the chrome and widgets repeated across the app
(sidebar, header, footer, navbar, modal, loader, score-card, charts,
audit-table, progress). None of the shipped pages fetch these at runtime.

**Why:** every page currently ships this markup inline instead. Two reasons:

1. **`file://` compatibility.** `fetch()` (used by `assets/js/include.js`)
   is blocked by the browser when a page is opened directly from disk
   (`file:///.../dashboard.html`) rather than served over `http(s)`. Keeping
   the sidebar/header markup inline means every page in this project still
   works if you just double-click the `.html` file — no local server
   required.
2. **Sync availability.** `assets/js/audit.js` reads the progress-ring and
   checklist elements synchronously on `DOMContentLoaded`. An async
   `fetch()`-based include would require extra "wait for the include, then
   re-run init" wiring for no real benefit on a single-audit-run page.

## Using these anyway

If you're serving the site over `http(s)` (e.g. via a bundler, `vite`,
`python -m http.server`, etc.) and would rather not hand-maintain copies of
this markup across every page, you can switch to live includes:

```html
<div data-include="sidebar"></div>
<div data-include="header"></div>
<script src="assets/js/include.js"></script>
<script>
  Components.includeAll().then(function () {
    document.dispatchEvent(new Event('components:ready'));
  });
</script>
```

After a fetch-based include of `sidebar.html`, re-run `app.js`'s
`highlightActiveNav()` and `initSidebar()` (they normally run on
`DOMContentLoaded`, before the fetch resolves) — for example by listening
for the `components:ready` event above.

## Data-driven components

Two components are meant to be rendered from data rather than copy-pasted,
via `assets/js/components.js` (`window.Components.renderScoreCard(...)` /
`window.Components.renderAuditRow(...)`):

- `score-card.html` — the static markup shown here is a filled-in example;
  `Components.renderScoreCard({ label, score })` returns the same markup
  as a string with the ring's `stroke-dashoffset` computed for any score.
- `audit-table.html` — the `<tr>` shape rendered into `#auditTableBody` is
  `Components.renderAuditRow(audit)`. See `history.html` / `assets/js/history.js`
  for the page that actually uses this.
