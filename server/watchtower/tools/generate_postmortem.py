"""generate_postmortem MCP tool.

Produces a structured Markdown postmortem draft for an incident,
anchoring on a service + window. Facts are drawn from the event store,
Prometheus, and Loki. Interpretation sections are left empty for Claude
to fill.

See docs/rfc-postmortem-generator.md for the design.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..config import Config
from ..db import connection
from ._correlate_helpers import (
    detect_log_bursts,
    detect_restart_deltas,
    Signal,
)


log = logging.getLogger(__name__)


TOOL_NAME = "generate_postmortem"


TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Generate a structured postmortem draft for an incident. Returns "
        "Markdown with these sections: Summary, Timeline, Impact, Root "
        "cause, Contributing factors, Remediation, Action items, Lessons "
        "learned, Appendix.\n\n"
        "Fact sections (Timeline, Impact, Remediation, Appendix) are "
        "pre-filled from the event store, Prometheus, Loki, and the "
        "approval audit log. Interpretation sections are intentionally "
        "empty — you (Claude) should fill them based on the facts. This "
        "separation is by design: an operator reading the postmortem "
        "should be able to tell which lines are ground truth and which "
        "are inference.\n\n"
        "Use this after an incident has resolved, OR to write a draft "
        "mid-incident that can be iterated on. If the incident isn't "
        "over yet, the Remediation section will be empty and you should "
        "note that."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "The affected service.",
            },
            "window_start_iso": {
                "type": "string",
                "description": (
                    "Incident start time (ISO-8601 UTC). If omitted, "
                    "defaults to window_minutes before window_end_iso or now."
                ),
            },
            "window_end_iso": {
                "type": "string",
                "description": (
                    "Incident end time (ISO-8601 UTC). If omitted, "
                    "defaults to now or the most recent resolve event for "
                    "the service."
                ),
            },
            "window_minutes": {
                "type": "integer",
                "default": 60,
                "minimum": 1,
                "maximum": 1440,
                "description": (
                    "Window width if start/end not specified. Default 60min."
                ),
            },
        },
        "required": ["service"],
    },
}


# ---------------------------------------------------------------- helpers ---

def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _most_recent_resolve(cfg: Config, service: str) -> Optional[datetime]:
    """Find the most recent incident_resolved timestamp for a service."""
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT timestamp FROM events
            WHERE service = %s AND event_type = 'incident_resolved'
            ORDER BY timestamp DESC LIMIT 1
            """,
            (service,),
        )
        row = cur.fetchone()
    return row["timestamp"] if row else None


def _resolve_window(cfg: Config, service: str, args: dict) -> tuple[datetime, datetime]:
    """Determine the (start, end) window from the provided arguments."""
    start = _parse_iso(args.get("window_start_iso"))
    end = _parse_iso(args.get("window_end_iso"))
    window_minutes = int(args.get("window_minutes", 60))

    if start and end:
        return start, end

    if end and not start:
        return end - timedelta(minutes=window_minutes), end

    if start and not end:
        return start, start + timedelta(minutes=window_minutes)

    # Neither provided — use most recent resolve as anchor, or now
    anchor = _most_recent_resolve(cfg, service) or datetime.now(timezone.utc)
    return anchor - timedelta(minutes=window_minutes), anchor


def _events_for_service(cfg: Config, service: str,
                        start: datetime, end: datetime) -> list[dict]:
    """All events for the service in the window."""
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT timestamp, event_type, severity, actor,
                   source_system, source_id, title, payload
            FROM events
            WHERE service = %s
              AND timestamp >= %s
              AND timestamp <= %s
            ORDER BY timestamp ASC
            """,
            (service, start, end),
        )
        return cur.fetchall()


def _change_events_before(cfg: Config, service: str,
                          start: datetime, widen_hours: int = 4) -> list[dict]:
    """Deploys / Terraform / config changes before the incident window."""
    lookback = start - timedelta(hours=widen_hours)
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT timestamp, event_type, actor, source_system, source_id, title
            FROM events
            WHERE service = %s
              AND timestamp >= %s
              AND timestamp <= %s
              AND event_type IN ('deploy', 'terraform_apply',
                                 'config_change', 'feature_flag')
            ORDER BY timestamp DESC
            """,
            (service, lookback, start),
        )
        return cur.fetchall()


def _remediations(cfg: Config, start: datetime, end: datetime) -> list[dict]:
    """Successful approved_remedy executions during the window."""
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.at, a.actor, a.exit_code, a.stdout,
                   r.runbook_id, r.remedy_id
            FROM approval_audit a
            LEFT JOIN approval_requests r ON r.id = a.proposal_id
            WHERE a.action = 'executed'
              AND a.at >= %s
              AND a.at <= %s
            ORDER BY a.at ASC
            """,
            (start, end),
        )
        return cur.fetchall()


# ----------------------------------------------------------- rendering -----

def _render_timeline(events: list[dict],
                     restart_signals: list[Signal],
                     log_burst_signals: list[Signal]) -> str:
    """Sorted timeline of all signals in the window."""
    rows: list[tuple[datetime, str]] = []

    for e in events:
        tag = f"[{e['source_system']}]"
        rows.append((e["timestamp"], f"{tag} {e['title']}"))

    for s in restart_signals:
        rows.append((s.timestamp, f"[metric] {s.summary}"))

    for s in log_burst_signals:
        rows.append((s.timestamp, f"[logs] {s.summary}"))

    rows.sort(key=lambda r: r[0])

    if not rows:
        return "_No signals recorded in this window._"

    lines = []
    for ts, text in rows:
        lines.append(f"- `{ts.strftime('%H:%M:%S')} UTC` {text}")
    return "\n".join(lines)


def _render_impact(events: list[dict], restart_signals: list[Signal],
                   log_burst_signals: list[Signal],
                   start: datetime, end: datetime) -> str:
    """Machine-readable impact statement."""
    pd_events = [e for e in events
                 if e["source_system"] == "pagerduty"]
    pd_open = [e for e in pd_events if e["event_type"] == "incident_open"]
    pd_resolved = [e for e in pd_events if e["event_type"] == "incident_resolved"]

    restart_count = sum(s.detail.get("delta", 0) for s in restart_signals)
    burst_bucket_count = len(log_burst_signals)
    log_burst_total_lines = sum(
        s.detail.get("count", 0) for s in log_burst_signals
    )

    duration = int((end - start).total_seconds() // 60)

    lines = []
    lines.append(f"- **Window:** {start.isoformat()} → {end.isoformat()} ({duration} min)")
    lines.append(f"- **PagerDuty incidents opened:** {len(pd_open)}")
    lines.append(f"- **PagerDuty incidents resolved:** {len(pd_resolved)}")
    lines.append(f"- **Container restarts (delta):** {int(restart_count)}")
    lines.append(f"- **Log burst buckets:** {burst_bucket_count} "
                 f"({log_burst_total_lines} error/warn lines)")
    if not (pd_open or restart_count or burst_bucket_count):
        lines.append("- _No clear quantitative impact signals. Consider if "
                     "this was a low-severity or transient event._")
    return "\n".join(lines)


def _render_change_history(changes: list[dict]) -> str:
    if not changes:
        return "_No deploys, Terraform applies, or config changes in the 4h before the incident._"
    lines = []
    for c in changes:
        lines.append(
            f"- `{c['timestamp'].strftime('%Y-%m-%d %H:%M')}` "
            f"[{c['source_system']}] {c['event_type']} — "
            f"{c['title']} (by {c.get('actor') or 'unknown'})"
        )
    return "\n".join(lines)


def _render_remediations(remediations: list[dict]) -> str:
    if not remediations:
        return ("_No approved remedies were executed during this window. "
                "Either the incident self-resolved, was manually remediated "
                "outside WatchTower, or remediation is still pending._")
    lines = []
    for r in remediations:
        stdout = (r.get("stdout") or "").strip().splitlines()[0][:120] if r.get("stdout") else "(no output)"
        lines.append(
            f"- `{r['at'].strftime('%H:%M:%S')} UTC` "
            f"**{r.get('runbook_id', '?')}/{r.get('remedy_id', '?')}** "
            f"executed by `{r['actor']}` — exit {r['exit_code']}, `{stdout}`"
        )
    return "\n".join(lines)


def _render_appendix(events: list[dict]) -> str:
    if not events:
        return "_No raw signals._"
    by_source: dict[str, list[dict]] = {}
    for e in events:
        by_source.setdefault(e["source_system"], []).append(e)

    lines = []
    for source in sorted(by_source):
        rows = by_source[source]
        lines.append(f"### {source} ({len(rows)})")
        for e in rows:
            lines.append(
                f"- `{e['timestamp'].strftime('%H:%M:%S')}` "
                f"[{e['event_type']}/{e['severity']}] {e['title']}"
            )
        lines.append("")
    return "\n".join(lines).strip()


# ---------------------------------------------------------- main entry ---

def run(cfg: Config, args: dict[str, Any]) -> str:
    service = args.get("service")
    if not service:
        return "Error: 'service' parameter is required."

    start, end = _resolve_window(cfg, service, args)

    log.info("generate_postmortem service=%s window=%s..%s",
             service, start.isoformat(), end.isoformat())

    # Gather all sources; each protected against failure
    events: list[dict] = []
    restart_signals: list[Signal] = []
    log_burst_signals: list[Signal] = []
    changes: list[dict] = []
    remediations: list[dict] = []

    try:
        events = _events_for_service(cfg, service, start, end)
    except Exception as exc:
        log.warning("Events fetch failed: %s", exc)

    try:
        restart_signals = detect_restart_deltas(service, start, end)
    except Exception as exc:
        log.warning("Restart delta fetch failed: %s", exc)

    try:
        log_burst_signals = detect_log_bursts(service, start, end, 60)
    except Exception as exc:
        log.warning("Log burst fetch failed: %s", exc)

    try:
        changes = _change_events_before(cfg, service, start)
    except Exception as exc:
        log.warning("Change events fetch failed: %s", exc)

    try:
        remediations = _remediations(cfg, start, end)
    except Exception as exc:
        log.warning("Remediations fetch failed: %s", exc)

    # Assemble markdown
    parts = []
    parts.append(f"# Postmortem: `{service}` incident")
    parts.append(f"**Window:** {start.isoformat()} → {end.isoformat()}")
    parts.append("")

    parts.append("## 1. Summary")
    parts.append(f"_[To be written by Claude based on the facts below.]_")
    parts.append("")

    parts.append("## 2. Timeline")
    parts.append(_render_timeline(events, restart_signals, log_burst_signals))
    parts.append("")

    parts.append("## 3. Impact")
    parts.append(_render_impact(
        events, restart_signals, log_burst_signals, start, end,
    ))
    parts.append("")

    parts.append("## 4. Recent changes before the incident")
    parts.append(_render_change_history(changes))
    parts.append("")

    parts.append("## 5. Root cause")
    parts.append("_[Claude: analyze the timeline + recent changes. "
                 "Cite specific events by timestamp.]_")
    parts.append("")

    parts.append("## 6. Contributing factors")
    parts.append("_[Claude: what made detection slow? what amplified impact? "
                 "Cite specific gaps.]_")
    parts.append("")

    parts.append("## 7. Remediation actions taken")
    parts.append(_render_remediations(remediations))
    parts.append("")

    parts.append("## 8. Action items")
    parts.append("_[Claude: specific, assigned, measurable. "
                 "Format: `[OWNER] action (by when)`.]_")
    parts.append("")

    parts.append("## 9. Lessons learned")
    parts.append("_[Claude: one paragraph of honest retrospective. "
                 "What would you do differently?]_")
    parts.append("")

    parts.append("---")
    parts.append("## Appendix: raw signals")
    parts.append(_render_appendix(events))

    return "\n".join(parts)