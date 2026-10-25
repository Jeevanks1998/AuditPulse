/* Small Chart.js wrapper (Chart.js must be loaded first). */

window.Charts = (function () {

  var instances = {};

  function destroy(canvasId) {
    if (instances[canvasId]) {
      instances[canvasId].destroy();
      delete instances[canvasId];
    }
  }

  // Radar chart
  function renderRadar(canvasId, labels, values, opts) {
    if (!window.Chart) return null;
    var canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    destroy(canvasId);

    opts = opts || {};
    instances[canvasId] = new window.Chart(canvas, {
      type: 'radar',
      data: {
        labels: labels,
        datasets: [{
          label: opts.datasetLabel || 'Score',
          data: values,
          backgroundColor: 'rgba(37, 99, 235, 0.15)',
          borderColor: '#2563EB',
          borderWidth: 2,
          pointBackgroundColor: '#2563EB',
          pointRadius: 3
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { r: { min: 0, max: 100, ticks: { display: false }, grid: { color: 'rgba(148,163,184,0.25)' } } },
        plugins: { legend: { display: false }, tooltip: { enabled: true } }
      }
    });
    return instances[canvasId];
  }

  // Line chart
  function renderTrendLine(canvasId, labels, values, opts) {
    if (!window.Chart) return null;
    var canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    destroy(canvasId);

    opts = opts || {};
    instances[canvasId] = new window.Chart(canvas, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: opts.datasetLabel || 'Trend',
          data: values,
          borderColor: opts.color || '#2563EB',
          backgroundColor: (opts.color || '#2563EB') + '22',
          fill: true,
          tension: 0.35,
          pointRadius: 0,
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { display: !!opts.showAxes, grid: { display: false } },
          y: { display: !!opts.showAxes, min: opts.min, max: opts.max, grid: { color: 'rgba(148,163,184,0.15)' } }
        },
        plugins: { legend: { display: false } }
      }
    });
    return instances[canvasId];
  }

  // Severity doughnut
  function renderSeverityDoughnut(canvasId, counts, opts) {
    if (!window.Chart) return null;
    var canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    destroy(canvasId);

    opts = opts || {};
    instances[canvasId] = new window.Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: ['High', 'Medium', 'Low'],
        datasets: [{
          data: [counts.high || 0, counts.medium || 0, counts.low || 0],
          backgroundColor: ['#EF4444', '#F59E0B', '#10B981'],
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '68%',
        plugins: { legend: { display: !!opts.showLegend, position: 'bottom' } }
      }
    });
    return instances[canvasId];
  }

  return {
    renderRadar: renderRadar,
    renderTrendLine: renderTrendLine,
    renderSeverityDoughnut: renderSeverityDoughnut,
    destroy: destroy
  };
})();
