"""correlate_signals MCP tool.

Given a service and a time window, pulls events + metric deltas + log bursts,
clusters them temporally, and returns an annotated Markdown timeline.

See docs/rfc-correlate-signals.md for the full design.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Config
from ..db import connection
from ._correlate_helpers import (
    Signal,
    cluster_signals,
    detect_log_bursts,
    detect_restart_deltas,
    format_timeline,
)


log = logging.getLogger(__name__)


TOOL_NAME = "correlate_signals"


TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Produce a correlated timeline of signals (events, metric deltas, log "
        "bursts) for a service over a time window. Signals that occur close "
        "together are grouped into clusters, each annotated with a "
        "rule-based interpretation (e.g. 'Probe failure → pod restart').\n\n"
        "Use this instead of chaining search_events + query_metrics + "
        "search_logs manually when you want a single synthesized view of "
        "what was happening on a service during an incident window. "
        "The tool handles temporal alignment; you provide context and "
        "recommendations.\n\n"
        "Scope: one service per call. For cluster-wide analysis, call "
        "multiple times across services or use suspect_rank instead."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "Service to correlate (e.g. 'checkoutservice').",
            },
            "window_minutes": {
                "type": "integer",
                "default": 30,
                "minimum": 1,
                "maximum": 1440,
                "description": "How far back from now to look. Default 30 min.",
            },
            "window_end_iso": {
                "type": "string",
                "description": (
                    "Optional: the end of the window as ISO-8601 UTC "
                    "(e.g. '2026-04-20T17:30:00Z'). If omitted, defaults to "
                    "now."
                ),
            },
            "bucket_seconds": {
                "type": "integer",
                "default": 60,
                "minimum": 10,
                "maximum": 600,
                "description": "Temporal clustering threshold (default 60s).",
            },
        },
        "required": ["service"],
    },
}


# Event puller

def _events_for_service(cfg: Config, service: str,
                        start: datetime, end: datetime) -> list[Signal]:
    """Pull events for a service in the window, convert to Signal objects."""
    sql = """
    SELECT timestamp, event_type, severity, service, actor, source_system,
           source_id, title, payload
    FROM events
    WHERE service = %s
      AND timestamp >= %s
      AND timestamp <= %s
    ORDER BY timestamp ASC
    LIMIT 200
    """
    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(sql, (service, start, end))
        rows = cur.fetchall()

    signals: list[Signal] = []
    for row in rows:
        payload = row["payload"] or {}
        reason = payload.get("reason") or ""
        k8s_type = payload.get("k8s_type") or ""
        summary_extra = f" ({k8s_type})" if k8s_type else ""
        signals.append(Signal(
            timestamp=row["timestamp"],
            signal_type="event",
            summary=f"{row['title']}{summary_extra}",
            detail={
                "event_type": row["event_type"],
                "severity": row["severity"],
                "reason": reason,
                "actor": row["actor"],
                "source": f"{row['source_system']}:{row['source_id']}",
                "payload": payload,
            },
        ))
    return signals


# Main 

def run(cfg: Config, args: dict[str, Any]) -> str:
    service = args.get("service")
    if not service:
        return "Error: 'service' parameter is required."

    window_minutes = int(args.get("window_minutes", 30))
    bucket_seconds = int(args.get("bucket_seconds", 60))

    # Resolve window end
    window_end_iso = args.get("window_end_iso")
    if window_end_iso:
        try:
            window_end = datetime.fromisoformat(window_end_iso.replace("Z", "+00:00"))
            if window_end.tzinfo is None:
                window_end = window_end.replace(tzinfo=timezone.utc)
        except ValueError as exc:
            return f"Error: invalid window_end_iso: {exc}"
    else:
        window_end = datetime.now(timezone.utc)

    window_start = window_end - timedelta(minutes=window_minutes)

    log.info(
        "correlate_signals service=%s window=%s..%s bucket=%ss",
        service, window_start.isoformat(), window_end.isoformat(), bucket_seconds,
    )

    # Gather signals from all three sources. Each source is independent;
    # a failure in one should not kill the whole analysis.
    all_signals: list[Signal] = []

    try:
        all_signals.extend(_events_for_service(cfg, service, window_start, window_end))
    except Exception as exc:
        log.warning("Event source failed: %s", exc)

    try:
        all_signals.extend(detect_restart_deltas(service, window_start, window_end))
    except Exception as exc:
        log.warning("Metric source failed: %s", exc)

    try:
        all_signals.extend(detect_log_bursts(service, window_start, window_end, bucket_seconds))
    except Exception as exc:
        log.warning("Log source failed: %s", exc)

    clusters = cluster_signals(all_signals, bucket_seconds)
    return format_timeline(service, window_start, window_end, clusters, bucket_seconds)