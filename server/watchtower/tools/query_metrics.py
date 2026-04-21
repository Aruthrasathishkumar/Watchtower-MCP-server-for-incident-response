"""query_metrics MCP tool.

Executes PromQL queries against Prometheus and returns results formatted
for Claude to reason over. Supports both instant queries and range queries.

Assumes Prometheus is reachable at WATCHTOWER_PROMETHEUS_URL (default
http://localhost:9090).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Any

from ..config import Config


log = logging.getLogger(__name__)


TOOL_NAME = "query_metrics"


TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": (
        "Execute a PromQL query against Prometheus and return the result. "
        "Use this for symptom-side investigation: container restart counts, "
        "pod readiness, CPU/memory usage, etc.\n\n"
        "IMPORTANT — scope of available metrics: WatchTower's Prometheus is "
        "currently scraping Kubernetes infrastructure (kube-state-metrics, "
        "cAdvisor, node-exporter). Online Boutique's microservices are NOT "
        "instrumented for Prometheus — they do not expose /metrics endpoints. "
        "Do not query gRPC or HTTP app-level metrics like "
        "`grpc_server_handled_total` or `grpc_server_handling_seconds_bucket` "
        "for services in the boutique namespace — those series are "
        "permanently empty and indicate a data gap, not a scrape failure.\n\n"
        "Useful metrics that ARE available for the boutique namespace:\n"
        "- kube_pod_container_status_restarts_total — restart counts\n"
        "- kube_pod_status_ready — readiness gauge\n"
        "- kube_pod_status_phase — Running/Pending/Failed\n"
        "- kube_pod_container_resource_requests — configured requests\n"
        "- kube_pod_container_resource_limits — configured limits\n"
        "- container_cpu_usage_seconds_total — cAdvisor CPU (use rate())\n"
        "- container_memory_working_set_bytes — cAdvisor memory\n\n"
        "For recent changes (deploys, config edits), use what_changed instead."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A PromQL expression. Examples: "
                    "'up{namespace=\"boutique\"}' (scrape health), "
                    "'rate(grpc_server_handled_total[1m])' (gRPC request rate), "
                    "'histogram_quantile(0.99, rate(grpc_server_handling_seconds_bucket[5m]))' "
                    "(p99 latency)."
                ),
            },
            "query_type": {
                "type": "string",
                "enum": ["instant", "range"],
                "default": "instant",
                "description": (
                    "'instant' returns current values. 'range' returns a "
                    "time series over the last window."
                ),
            },
            "window": {
                "type": "string",
                "default": "5m",
                "description": (
                    "For range queries: how far back to look (e.g. '5m', '1h'). "
                    "Ignored for instant queries."
                ),
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
        raise ValueError(f"Invalid window '{window}'. Use e.g. '5m', '1h'.")
    return int(m.group(1)) * _WINDOW_TO_SECONDS[m.group(2).lower()]


def _prometheus_url() -> str:
    return os.environ.get("WATCHTOWER_PROMETHEUS_URL", "http://localhost:9090")


def _query_instant(promql: str) -> dict[str, Any]:
    url = _prometheus_url() + "/api/v1/query?" + urllib.parse.urlencode({"query": promql})
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _query_range(promql: str, window_seconds: int) -> dict[str, Any]:
    import time
    end = int(time.time())
    start = end - window_seconds
    # Aim for ~60 data points regardless of window length
    step = max(1, window_seconds // 60)
    params = {"query": promql, "start": start, "end": end, "step": step}
    url = _prometheus_url() + "/api/v1/query_range?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _format_instant(result: dict[str, Any]) -> str:
    data = result.get("data", {})
    series = data.get("result", [])
    if not series:
        return f"No results. (Query: `{result.get('data', {}).get('resultType', '?')}`)"

    lines = [f"Returned {len(series)} series. Sampled values:", ""]
    for s in series[:20]:  # cap to avoid overwhelming Claude
        labels = s.get("metric", {})
        value = s.get("value", ["?", "?"])[1]
        labels_str = ", ".join(f"{k}={v!r}" for k, v in sorted(labels.items()))
        lines.append(f"- {{{labels_str}}} = {value}")
    if len(series) > 20:
        lines.append(f"- ... ({len(series) - 20} more series omitted)")
    return "\n".join(lines)


def _format_range(result: dict[str, Any]) -> str:
    data = result.get("data", {})
    series = data.get("result", [])
    if not series:
        return "No results."

    lines = [f"Returned {len(series)} time series. Per-series min/max/last:", ""]
    for s in series[:15]:
        labels = s.get("metric", {})
        values = s.get("values", [])
        if not values:
            continue
        nums = [float(v[1]) for v in values]
        labels_str = ", ".join(f"{k}={v!r}" for k, v in sorted(labels.items()))
        lines.append(
            f"- {{{labels_str}}}: "
            f"min={min(nums):.4g}, max={max(nums):.4g}, last={nums[-1]:.4g}, samples={len(nums)}"
        )
    if len(series) > 15:
        lines.append(f"- ... ({len(series) - 15} more series omitted)")
    return "\n".join(lines)


def run(cfg: Config, args: dict[str, Any]) -> str:
    """Execute the query_metrics tool."""
    query = args.get("query")
    if not query:
        return "Error: 'query' parameter is required."

    query_type = args.get("query_type", "instant")
    window = args.get("window", "5m")

    log.info("query_metrics type=%s query=%s", query_type, query)

    try:
        if query_type == "range":
            window_seconds = _parse_window_seconds(window)
            result = _query_range(query, window_seconds)
        else:
            result = _query_instant(query)
    except urllib.error.URLError as exc:
        return (
            f"Error: Could not reach Prometheus at {_prometheus_url()}. "
            f"Is `kubectl port-forward` running? Details: {exc}"
        )
    except Exception as exc:
        return f"Error: {exc}"

    if result.get("status") != "success":
        return f"Prometheus error: {result.get('error', 'unknown')}"

    if query_type == "range":
        return _format_range(result)
    return _format_instant(result)