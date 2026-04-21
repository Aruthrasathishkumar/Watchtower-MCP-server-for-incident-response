"""what_changed MCP tool.

Rewind-phase tool: given a time window (default: last 30 min) and optional
service filter, returns *change* events only — the things likely to have
caused an incident.

Change events are: deploy, terraform_apply, config_change, feature_flag.
Everything else (metrics, logs, alerts) is intentionally excluded.

Output is grouped by service so Claude can reason "these services had the
most changes in the window" — a natural first heuristic during triage.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..config import Config
from ..db import connection


log = logging.getLogger(__name__)


TOOL_NAME = "what_changed"

CHANGE_EVENT_TYPES = ("deploy", "terraform_apply", "config_change", "feature_flag")

TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Incident-response triage: list the *changes* (deploys, Terraform "
        "applies, config edits, feature flag flips) that happened in the "
        "recent past. Use this FIRST when investigating an incident, "
        "before looking at metrics or logs. Results are grouped by service, "
        "most recent first. For generic event search, use `search_events` instead."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "window": {
                "type": "string",
                "description": (
                    "How far back to look. Accepts e.g. '30m', '2h', '1d'. "
                    "Defaults to '30m'."
                ),
                "default": "30m",
            },
            "service": {
                "type": "string",
                "description": (
                    "Optional service name to focus on (e.g. 'checkout'). "
                    "If omitted, returns changes across all services."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Maximum events to return.",
                "default": 20,
                "minimum": 1,
                "maximum": 200,
            },
        },
    },
}


_WINDOW_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)

_UNIT_TO_INTERVAL = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
}


def _parse_window(window: str) -> tuple[int, str]:
    """Parse '30m', '2h', '1d' into (amount, unit_name_for_postgres).

    Returns a tuple like (30, 'minutes'). Raises ValueError on bad input.
    """
    match = _WINDOW_RE.match(window)
    if not match:
        raise ValueError(
            f"Invalid window '{window}'. Use formats like '30m', '2h', '1d'."
        )
    amount = int(match.group(1))
    unit = _UNIT_TO_INTERVAL[match.group(2).lower()]
    return amount, unit


def run(cfg: Config, args: dict[str, Any]) -> str:
    """Execute the what_changed tool."""
    window = args.get("window", "30m")
    service = args.get("service")
    limit = min(int(args.get("limit", 20)), 200)

    try:
        amount, unit = _parse_window(window)
    except ValueError as exc:
        return f"Error: {exc}"

    interval_literal = f"{amount} {unit}"

    # Build a placeholder string like "(%s,%s,%s,%s)" sized to CHANGE_EVENT_TYPES.
    # psycopg treats each %s as one parameter, so we expand the tuple explicitly.
    placeholders = ",".join(["%s"] * len(CHANGE_EVENT_TYPES))

    sql = [
        "SELECT id, timestamp, event_type, severity, service, actor,",
        "       source_system, source_id, title, payload",
        "FROM events",
        f"WHERE timestamp >= NOW() - INTERVAL '{interval_literal}'",
        f"  AND event_type IN ({placeholders})",
    ]
    params: list[Any] = list(CHANGE_EVENT_TYPES)

    if service:
        sql.append("  AND service = %s")
        params.append(service)

    sql.append("ORDER BY service NULLS LAST, timestamp DESC")
    sql.append("LIMIT %s")
    params.append(limit)

    query = "\n".join(sql)
    log.info("what_changed window=%s service=%s limit=%s",
             window, service, limit)

    with connection(cfg) as conn, conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    if not rows:
        return (
            f"No changes found in the last {interval_literal}"
            + (f" for service '{service}'" if service else "")
            + "."
        )

    # Group by service for Claude's reasoning
    by_service: dict[str, list[dict]] = {}
    for row in rows:
        svc = row["service"] or "(unknown)"
        by_service.setdefault(svc, []).append(row)

    # Build output: summary header + per-service change list
    out_lines = [
        f"Found {len(rows)} change(s) in the last {interval_literal}"
        + (f" for service '{service}'" if service else " across all services")
        + f". Grouped by service, most recent first:",
        "",
    ]
    for svc in sorted(by_service, key=lambda s: -len(by_service[s])):
        changes = by_service[svc]
        out_lines.append(f"### {svc} ({len(changes)} change{'s' if len(changes) != 1 else ''})")
        for row in changes:
            out_lines.append(json.dumps(
                {
                    "timestamp": row["timestamp"].isoformat(),
                    "event_type": row["event_type"],
                    "severity": row["severity"],
                    "actor": row["actor"],
                    "title": row["title"],
                    "source": f"{row['source_system']}:{row['source_id']}",
                    "payload": row["payload"],
                },
                default=str,
            ))
        out_lines.append("")

    return "\n".join(out_lines).strip()