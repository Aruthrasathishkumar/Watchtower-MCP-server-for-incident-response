// WatchTower incident detail view

const urlParams = new URLSearchParams(window.location.search);
const eventId = urlParams.get('id');

async function loadIncident() {
  try {
    const resp = await fetch('data/events.json');
    const all = await resp.json();
    const event = all.find(e => e.id === eventId);

    if (!event) {
      render404();
      return;
    }

    renderIncident(event, all);
  } catch (err) {
    document.getElementById('detail-container').innerHTML =
      '<div class="empty">Could not load event data.</div>';
    console.error(err);
  }
}

function render404() {
  document.getElementById('detail-container').innerHTML = `
    <div class="panel">
      <h2>Event not found</h2>
      <div class="empty">
        No event with that id. <a href="index.html">Back to timeline</a>
      </div>
    </div>
  `;
}

function renderIncident(event, all) {
  const ts = new Date(event.timestamp);
  const windowMin = 30;
  const windowStart = new Date(ts.getTime() - windowMin * 60000);
  const windowEnd = new Date(ts.getTime() + windowMin * 60000);

  // Find related events: same service, within ±30 min
  const related = all
    .filter(e =>
      e.id !== event.id &&
      e.service === event.service &&
      new Date(e.timestamp) >= windowStart &&
      new Date(e.timestamp) <= windowEnd
    )
    .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

  const container = document.getElementById('detail-container');
  container.innerHTML = `
    <div class="panel">
      <h2>Event ${escapeHtml(event.id.substring(0, 8))}…</h2>
      <div class="kv-list">
        <div class="kv"><div class="k">Timestamp</div><div class="v">${ts.toISOString()}</div></div>
        <div class="kv"><div class="k">Source</div><div class="v"><span class="event-source ${event.source_system}">${event.source_system}</span> / ${escapeHtml(event.source_id)}</div></div>
        <div class="kv"><div class="k">Type</div><div class="v">${escapeHtml(event.event_type)}</div></div>
        <div class="kv"><div class="k">Severity</div><div class="v"><span class="event-severity ${event.severity}">${event.severity}</span></div></div>
        <div class="kv"><div class="k">Service</div><div class="v">${event.service ? escapeHtml(event.service) : '<em>none</em>'}</div></div>
        <div class="kv"><div class="k">Actor</div><div class="v">${event.actor ? escapeHtml(event.actor) : '<em>none</em>'}</div></div>
        <div class="kv"><div class="k">Title</div><div class="v">${escapeHtml(event.title)}</div></div>
      </div>
    </div>

    <div class="detail-grid">
      <div class="panel">
        <h2>Payload</h2>
        <pre class="json">${escapeHtml(JSON.stringify(event.payload, null, 2))}</pre>
      </div>

      <div class="panel">
        <h2>Related signals (±${windowMin}min, same service)</h2>
        ${related.length === 0
          ? '<div class="empty">No related events in this window.</div>'
          : '<div class="timeline">' + related.map(e => {
              const rts = new Date(e.timestamp);
              const timeStr = rts.toLocaleString('en-US', {
                month: 'short', day: '2-digit',
                hour: '2-digit', minute: '2-digit', second: '2-digit',
                hour12: false,
              });
              return `
                <div class="event-row" onclick="window.location.href='incident.html?id=${e.id}'">
                  <span class="event-time">${timeStr}</span>
                  <span class="event-severity ${e.severity}">${e.severity}</span>
                  <span class="event-source ${e.source_system}">${e.source_system}</span>
                  <span>${escapeHtml(e.title)}</span>
                </div>
              `;
            }).join('') + '</div>'
        }
      </div>
    </div>

    <div class="panel">
      <h2>Back</h2>
      <div class="kv-list">
        <a href="index.html" style="color: var(--accent); padding: 6px 0; display: inline-block;">← Back to timeline</a>
      </div>
    </div>
  `;
}

function escapeHtml(s) {
  if (s == null) return '';
  const div = document.createElement('div');
  div.textContent = String(s);
  return div.innerHTML;
}

loadIncident();