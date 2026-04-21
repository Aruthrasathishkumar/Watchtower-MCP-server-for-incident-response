// WatchTower approval queue view

async function loadData() {
  try {
    const [reqResp, auditResp] = await Promise.all([
      fetch('data/approvals.json'),
      fetch('data/audit.json'),
    ]);
    const approvals = await reqResp.json();
    const audit = await auditResp.json();

    renderApprovals(approvals);
    renderAudit(audit);
  } catch (err) {
    document.getElementById('approvals-list').innerHTML =
      '<div class="empty">Could not load approval data.</div>';
    document.getElementById('audit-list').innerHTML = '';
    console.error(err);
  }
}

function renderApprovals(approvals) {
  const container = document.getElementById('approvals-list');
  if (approvals.length === 0) {
    container.innerHTML = '<div class="empty">No approval requests yet.</div>';
    return;
  }

  container.innerHTML = approvals.map(a => {
    const rts = new Date(a.requested_at);
    const timeStr = rts.toLocaleString('en-US', {
      month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
    const rationaleShort = (a.rationale || '').substring(0, 300);
    return `
      <div class="approval-row">
        <div class="approval-header">
          <span>
            <strong>${escapeHtml(a.runbook_id)}</strong> /
            ${escapeHtml(a.remedy_id)}
          </span>
          <span class="status ${a.status}">${a.status}</span>
        </div>
        <div style="color: var(--text-dim); font-size: 12px;">
          ${timeStr} · requested by ${escapeHtml(a.requested_by || 'claude')} · id <code>${a.id.substring(0, 8)}…</code>
        </div>
        <div class="approval-rationale">${escapeHtml(rationaleShort)}${rationaleShort.length < (a.rationale || '').length ? '…' : ''}</div>
      </div>
    `;
  }).join('');
}

function renderAudit(audit) {
  const container = document.getElementById('audit-list');
  if (audit.length === 0) {
    container.innerHTML = '<div class="empty">Audit log is empty.</div>';
    return;
  }

  container.innerHTML = audit.map(a => {
    const ts = new Date(a.at);
    const timeStr = ts.toLocaleString('en-US', {
      month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    });
    const actionClass = ['executed'].includes(a.action) ? 'executed'
      : ['approved'].includes(a.action) ? 'approved'
      : ['denied', 'invalid_token', 'replay_attempt', 'execution_failed', 'expired_token'].includes(a.action) ? 'denied'
      : 'pending';
    return `
      <div class="event-row">
        <span class="event-time">${timeStr}</span>
        <span class="status ${actionClass}" style="font-size: 11px;">${a.action}</span>
        <span class="event-source" style="background: var(--bg); color: var(--text-dim);">
          ${escapeHtml(a.actor || '?')}
        </span>
        <span>
          ${a.exit_code !== null && a.exit_code !== undefined
            ? `exit ${a.exit_code}`
            : '<em>—</em>'}
          ${a.stdout ? ` · <code style="color:var(--text-dim);">${escapeHtml((a.stdout || '').split('\n')[0].substring(0, 60))}</code>` : ''}
        </span>
      </div>
    `;
  }).join('');
}

function escapeHtml(s) {
  if (s == null) return '';
  const div = document.createElement('div');
  div.textContent = String(s);
  return div.innerHTML;
}

loadData();