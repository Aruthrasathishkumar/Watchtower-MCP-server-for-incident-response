"""search_logs MCP tool.

Queries Loki for log lines matching a LogQL expression.
Assumes Loki is reachable at WATCHTOWER_LOKI_URL (default
http://localhost:3100).
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..config import Config


log = logging.getLogger(__name__)


TOOL_NAME = "search_logs"


TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Search application logs in Loki using LogQL. Use for application-level "
        "investigation: error messages, stack traces, specific request IDs.\n\n"
        "LogQL quick reference:\n"
        "- Label selector (required): `{namespace=\"boutique\", container=\"server\"}`\n"
        "- Common labels: namespace, pod, container, app, job\n"
        "- Contain filter: `|= \"error\"` (case-sensitive), `|~ \"(?i)error\"` (regex)\n"
        "- Exclude filter: `!= \"healthz\"`\n"
        "- Combine: `{namespace=\"boutique\", app=\"checkoutservice\"} |= \"error\" != \"context canceled\"`\n\n"
        "Returns the most-recent matching log lines. For symptom investigation, "
        "combine with what_changed (for causes) and query_metrics (for system state)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A LogQL expression. MUST include a label selector in braces. "
                    "Example: `{namespace=\"boutique\", app=\"checkoutservice\"} |= \"error\"`"
                ),
            },
            "window": {
                "type": "string",
                "default": "1h",
                "description": "How far back to search. e.g. '15m', '1h', '6h', '1d'.",
            },
            "limit": {
                "type": "integer",
                "default": 30,
                "minimum": 1,
                "maximum": 200,
                "description": "Maximum log lines to return.",
            },
        },
        "required": ["query"],
    },
}


_WINDOW_TO_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_window_seconds(window: str) -> int:
    import re
    m = re.match(r"^\s*(\d+)\s*([smhd])\s*$", window, re.IGNORECASE)
    if not m:
        raise ValueError(f"Invalid window '{window}'. Use e.g. '15m', '1h', '6h'.")
    return int(m.group(1)) * _WINDOW_TO_SECONDS[m.group(2).lower()]


def _loki_url() -> str:
    return os.environ.get("WATCHTOWER_LOKI_URL", "http://localhost:3100")


def _query_range(logql: str, window_seconds: int, limit: int) -> dict[str, Any]:
    end_ns = int(time.time() * 1_000_000_000)
    start_ns = end_ns - window_seconds * 1_000_000_000
    params = {
        "query": logql,
        "start": start_ns,
        "end": end_ns,
        "limit": limit,
        "direction": "backward",  # newest first
    }
    url = _loki_url() + "/loki/api/v1/query_range?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _format_streams(result: dict[str, Any], limit: int) -> str:
    data = result.get("data", {})
    streams = data.get("result", [])
    if not streams:
        return "No matching log lines found in the window."

    # Flatten all (timestamp, line, stream_labels) tuples and sort newest first
    entries: list[tuple[str, str, dict]] = []
    for stream in streams:
        labels = stream.get("stream", {})
        for ts_ns_str, line in stream.get("values", []):
            entries.append((ts_ns_str, line, labels))
    entries.sort(key=lambda e: -int(e[0]))
    entries = entries[:limit]

    # Format as a human-readable log dump
    lines = [f"Found {len(entries)} matching log lines (newest first):", ""]
    for ts_ns_str, line, labels in entries:
        ts_seconds = int(ts_ns_str) / 1_000_000_000
        ts_iso = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts_seconds))
        pod = labels.get("pod", "?")
        container = labels.get("container", "?")
        line_short = line.rstrip()[:500]
        lines.append(f"[{ts_iso} UTC] {pod}/{container}: {line_short}")
    return "\n".join(lines)


def run(cfg: Config, args: dict[str, Any]) -> str:
    """Execute the search_logs tool."""
    query = args.get("query")
    if not query:
        return "Error: 'query' parameter is required (a LogQL expression)."

    window = args.get("window", "1h")
    limit = min(int(args.get("limit", 30)), 200)

    try:
        window_seconds = _parse_window_seconds(window)
    except ValueError as exc:
        return f"Error: {exc}"

    log.info("search_logs window=%s limit=%s query=%s", window, limit, query)

    try:
        result = _query_range(query, window_seconds, limit)
    except urllib.error.URLError as exc:
        return (
            f"Error: Could not reach Loki at {_loki_url()}. "
            f"Is `kubectl port-forward -n logging svc/loki 3100:3100` running? "
            f"Details: {exc}"
        )
    except Exception as exc:
        return f"Error: {exc}"

    if result.get("status") != "success":
        return f"Loki error: {result.get('error', 'unknown')}"

    return _format_streams(result, limit)