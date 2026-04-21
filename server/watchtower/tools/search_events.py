"""search_events MCP tool.

Generic event-store search. Filters: service, event_type, severity, limit.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..config import Config
from ..db import connection


log = logging.getLogger(__name__)


TOOL_NAME = "search_events"

TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Search the WatchTower event store. "
        "Returns up to `limit` most-recent events matching the filters. "
        "Events include deploys, Kubernetes events, metric anomalies, "
        "log bursts, alerts, Slack messages, and incident records."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "Filter by service name (e.g. 'checkout').",
            },
            "event_type": {
                "type": "string",
                "enum": [
                    "deploy", "terraform_apply", "k8s_event", "feature_flag",
                    "config_change", "metric_anomaly", "log_burst",
                    "trace_error", "alert", "slack_msg",
                    "incident_open", "incident_resolved",
                ],
                "description": "Filter by event type.",
            },
            "severity": {
                "type": "string",
                "enum": ["info", "warning", "error", "critical"],
                "description": "Filter by severity level.",
            },
            "limit": {
                "type": "integer",
                "default": 10,
                "minimum": 1,
                "maximum": 100,
                "description": "Maximum number of events to return.",
            },
        },
    },
}


def run(cfg: Config, args: dict[str, Any]) -> str:
    """Execute the search_events tool with the given arguments."""
    service = args.get("service")
    event_type = args.get("event_type")
    severity = args.get("severity")
    limit = min(int(args.get("limit", 10)), 100)

    sql = [
        "SELECT id, timestamp, event_type, severity, service, actor,",
        "       source_system, source_id, title, payload",
        "FROM events",
        "WHERE 1=1",
    ]
    params: list[Any] = []
    if service:
        sql.append("AND service = %s")
        params.append(service)
    if event_type:
        sql.append("AND event_type = %s")
        params.append(event_type)
    if severity:
        sql.append("AND severity = %s")
        params.append(severity)
    sql.append("ORDER BY timestamp DESC")
    sql.append("LIMIT %s")
    params.append(limit)

    query = "\n".join(sql)
    log.info("search_events filters=%s limit=%s",
             {k: v for k, v in args.items() if v is not None}, limit)

    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    if not rows:
        return "No events found matching the filters."

    lines = []
    for row in rows:
        lines.append(json.dumps(
            {
                "id": str(row["id"]),
                "timestamp": row["timestamp"].isoformat(),
                "event_type": row["event_type"],
                "severity": row["severity"],
                "service": row["service"],
                "actor": row["actor"],
                "source_system": row["source_system"],
                "source_id": row["source_id"],
                "title": row["title"],
                "payload": row["payload"],
            },
            default=str,
        ))
    return "\n".join(lines)