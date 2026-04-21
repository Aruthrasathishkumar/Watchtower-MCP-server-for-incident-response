// WatchTower timeline view

let allEvents = [];

async function loadData() {
  try {
    const resp = await fetch('data/events.json');
    allEvents = await resp.json();
    populateFilters();
    renderStats();
    applyFilters();
  } catch (err) {
    document.getElementById('timeline').innerHTML =
      '<div class="empty">Could not load events.json. ' +
      'Run <code>python scripts/export_frontend_data.py</code> and refresh.</div>';
    console.error(err);
  }
}

function populateFilters() {
  const services = [...new Set(allEvents.map(e => e.service).filter(Boolean))].sort();
  const sources = [...new Set(allEvents.map(e => e.source_system))].sort();

  const svcSelect = document.getElementById('filter-service');
  services.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s;
    svcSelect.appendChild(opt);
  });

  const srcSelect = document.getElementById('filter-source');
  sources.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s;
    srcSelect.appendChild(opt);
  });

  svcSelect.addEventListener('change', applyFilters);
  srcSelect.addEventListener('change', applyFilters);
  document.getElementById('filter-severity').addEventListener('change', applyFilters);
}

function renderStats() {
  const totalEvents = allEvents.length;
  const sources = new Set(allEvents.map(e => e.source_system)).size;
  const services = new Set(allEvents.map(e => e.service).filter(Boolean)).size;
  const errors = allEvents.filter(
    e => e.severity === 'error' || e.severity === 'critical'
  ).length;

  const container = document.getElementById('stats');
  container.innerHTML = [
    ['Events ingested', totalEvents],
    ['Source systems', sources],
    ['Services tracked', services],
    ['Errors / critical', errors],
  ].map(([label, value]) => `
    <div class="stat-card">
      <div class="stat-label">${label}</div>
      <div class="stat-value">${value}</div>
    </div>
  `).join('');
}

function applyFilters() {
  const svc = document.getElementById('filter-service').value;
  const src = document.getElementById('filter-source').value;
  const sev = document.getElementById('filter-severity').value;

  const filtered = allEvents.filter(e =>
    (!svc || e.service === svc) &&
    (!src || e.source_system === src) &&
    (!sev || e.severity === sev)
  );

  renderTimeline(filtered);
}

function renderTimeline(events) {
  const container = document.getElementById('timeline');
  if (events.length === 0) {
    container.innerHTML = '<div class="empty">No events match the current filters.</div>';
    return;
  }

  container.innerHTML = events.slice(0, 200).map(e => {
    const ts = new Date(e.timestamp);
    const timeStr = ts.toLocaleString('en-US', {
      month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    });
    const service = e.service
      ? `<span class="event-service">${e.service}</span>`
      : '';
    return `
      <div class="event-row" onclick="viewIncident('${e.id}')">
        <span class="event-time">${timeStr}</span>
        <span class="event-severity ${e.severity}">${e.severity}</span>
        <span class="event-source ${e.source_system}">${e.source_system}</span>
        <span>
          ${escapeHtml(e.title)}
          ${service}
        </span>
      </div>
    `;
  }).join('');
}

function viewIncident(id) {
  window.location.href = `incident.html?id=${encodeURIComponent(id)}`;
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s || '';
  return div.innerHTML;
}

loadData();