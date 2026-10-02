// Fake analytics for the fixture site: GA4-style collect hits + a dataLayer.
// Hits only fire after the visitor accepted cookies (cookie "consent=yes").
window.dataLayer = window.dataLayer || [];
function consentGiven() { return document.cookie.indexOf('consent=yes') !== -1; }
var __hit = 0;
function ga(en, params) {
  if (!consentGiven()) return;
  var q = '_s=' + (++__hit) + '&v=2&tid=G-JOURNEY&en=' + encodeURIComponent(en) + '&dl=' + encodeURIComponent(location.href);
  for (var k in (params || {})) q += '&ep.' + k + '=' + encodeURIComponent(params[k]);
  new Image().src = 'http://www.google-analytics.com:PORT/g/collect?' + q;
}
function track(ev, params) { if (!consentGiven()) return; window.dataLayer.push(Object.assign({ event: ev }, params || {})); }
document.addEventListener('DOMContentLoaded', function () {
  if (consentGiven()) ga('page_view');
  var banner = document.getElementById('cookie-banner');
  if (banner && !consentGiven()) banner.style.display = 'block';
  var acc = document.getElementById('cb-accept');
  if (acc) acc.onclick = function () { document.cookie = 'consent=yes; path=/'; banner.style.display = 'none'; ga('page_view'); };
  var rej = document.getElementById('cb-reject');
  if (rej) rej.onclick = function () { document.cookie = 'consent=no; path=/'; banner.style.display = 'none'; };
});
