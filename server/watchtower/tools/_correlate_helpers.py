"""Helpers for the correlate_signals tool.

Kept separate from the main tool file for readability and testability.
"""
from __future__ import annotations

import json
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


# Signal shape 

@dataclass
class Signal:
    """One signal on the correlation timeline."""
    timestamp: datetime          # UTC
    signal_type: str             # "event", "metric_delta", "log_burst"
    summary: str                 # one-line human-readable description
    detail: dict                 # additional structured info


# Prometheus restart-count delta helper

def _prom_url() -> str:
    return os.environ.get("WATCHTOWER_PROMETHEUS_URL", "http://localhost:9090")


def _prom_instant(promql: str, at: datetime) -> list[dict]:
    """Execute a Prometheus instant query at a specific time."""
    url = _prom_url() + "/api/v1/query?" + urllib.parse.urlencode({
        "query": promql,
        "time": at.timestamp(),
    })
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("status") != "success":
        return []
    return data.get("data", {}).get("result", [])


def detect_restart_deltas(service: str, window_start: datetime,
                          window_end: datetime) -> list[Signal]:
    """Return signals for any container restart counts that increased in the window."""
    # Query at the start and end of the window and diff the results.
    # Boutique's labels: {namespace="boutique", pod=~"<service>-.*"}
    q = (
        f'kube_pod_container_status_restarts_total'
        f'{{namespace="boutique",pod=~"{service}-.*"}}'
    )

    try:
        before = _prom_instant(q, window_start)
        after = _prom_instant(q, window_end)
    except (urllib.error.URLError, Exception):
        return []

    # Build {pod -> count} maps
    def as_map(results: list[dict]) -> dict[str, float]:
        return {
            r["metric"].get("pod", "?"): float(r.get("value", [0, "0"])[1])
            for r in results
        }

    before_map = as_map(before)
    after_map = as_map(after)

    signals: list[Signal] = []
    for pod, after_count in after_map.items():
        before_count = before_map.get(pod, 0.0)
        delta = after_count - before_count
        if delta > 0:
            # Emit a signal at the window_end — we don't know the exact moment
            # of the restart without a range query, which is fine for clustering.
            signals.append(Signal(
                timestamp=window_end,
                signal_type="metric_delta",
                summary=(
                    f"Container restart count for pod {pod} "
                    f"increased by {int(delta)} "
                    f"(from {int(before_count)} to {int(after_count)})"
                ),
                detail={"pod": pod, "delta": int(delta)},
            ))
    return signals


# Loki log-burst helper

def _loki_url() -> str:
    return os.environ.get("WATCHTOWER_LOKI_URL", "http://localhost:3100")


def _loki_range(logql: str, start: datetime, end: datetime,
                limit: int = 1000) -> list[tuple[int, str, dict]]:
    """Return (timestamp_ns, line, stream_labels) tuples for a LogQL query."""
    params = {
        "query": logql,
        "start": int(start.timestamp() * 1e9),
        "end": int(end.timestamp() * 1e9),
        "limit": limit,
        "direction": "forward",
    }
    url = _loki_url() + "/loki/api/v1/query_range?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("status") != "success":
        return []

    out: list[tuple[int, str, dict]] = []
    for stream in data.get("data", {}).get("result", []):
        labels = stream.get("stream", {})
        for ts_ns_str, line in stream.get("values", []):
            out.append((int(ts_ns_str), line, labels))
    return out


def detect_log_bursts(service: str, window_start: datetime,
                      window_end: datetime,
                      bucket_seconds: int = 60) -> list[Signal]:
    """Detect per-bucket error/warning log bursts for a service.

    Simple heuristic: bucketise error-level log lines, flag buckets whose
    count exceeds 3x the median bucket count.
    """
    logql = (
        f'{{namespace="boutique",app="{service}"}} '
        f'|~ "(?i)(error|warning|fatal|panic)"'
    )
    try:
        entries = _loki_range(logql, window_start, window_end, limit=1000)
    except (urllib.error.URLError, Exception):
        return []

    if not entries:
        return []

    # Bucketise
    start_ns = int(window_start.timestamp() * 1e9)
    bucket_ns = bucket_seconds * 1_000_000_000
    buckets: dict[int, list[tuple[int, str]]] = {}
    for ts_ns, line, _labels in entries:
        idx = (ts_ns - start_ns) // bucket_ns
        buckets.setdefault(idx, []).append((ts_ns, line))

    if not buckets:
        return []

    counts = [len(v) for v in buckets.values()]
    # Median and threshold. Minimum threshold of 3 to avoid flagging quiet buckets.
    median = statistics.median(counts) if counts else 0
    threshold = max(3, int(median * 3))

    signals: list[Signal] = []
    for idx, lines in sorted(buckets.items()):
        if len(lines) < threshold:
            continue
        bucket_start_ns = start_ns + idx * bucket_ns
        ts = datetime.fromtimestamp(bucket_start_ns / 1e9, tz=timezone.utc)
        # Sample the first line for the summary
        sample_line = lines[0][1].rstrip()[:200]
        signals.append(Signal(
            timestamp=ts,
            signal_type="log_burst",
            summary=(
                f"Log burst: {len(lines)} error/warning lines in "
                f"{bucket_seconds}s (threshold {threshold}). Sample: {sample_line}"
            ),
            detail={
                "count": len(lines),
                "bucket_seconds": bucket_seconds,
                "sample_line": sample_line,
            },
        ))
    return signals


# Clustering

@dataclass
class Cluster:
    """A group of signals close together in time."""
    signals: list[Signal]

    @property
    def start(self) -> datetime:
        return min(s.timestamp for s in self.signals)

    @property
    def end(self) -> datetime:
        return max(s.timestamp for s in self.signals)

    @property
    def span_seconds(self) -> int:
        return int((self.end - self.start).total_seconds())


def cluster_signals(signals: list[Signal], bucket_seconds: int) -> list[Cluster]:
    """Group signals into temporal clusters.

    Two signals are in the same cluster if their timestamps are within
    bucket_seconds of each other (considering the chain of neighbours).
    """
    if not signals:
        return []

    sorted_signals = sorted(signals, key=lambda s: s.timestamp)
    clusters: list[Cluster] = []
    current: list[Signal] = [sorted_signals[0]]

    for sig in sorted_signals[1:]:
        gap = (sig.timestamp - current[-1].timestamp).total_seconds()
        if gap <= bucket_seconds:
            current.append(sig)
        else:
            clusters.append(Cluster(signals=current))
            current = [sig]
    clusters.append(Cluster(signals=current))
    return clusters


# Interpretation rules 

def interpret_cluster(cluster: Cluster) -> str:
    """Produce a one-phrase interpretation of the cluster's signal mix."""
    types = {s.signal_type for s in cluster.signals}
    # Look at event reasons if any events are present
    event_reasons = set()
    for s in cluster.signals:
        if s.signal_type == "event":
            reason = s.detail.get("reason", "").lower()
            if reason:
                event_reasons.add(reason)

    # Check for cluster-level events
    deploy_like = {"successfulcreate", "scheduled", "started", "pulled", "created"}
    probe_like = {"unhealthy", "backoff", "failed"}
    runtime_like = {"sandboxchanged", "failedsync"}

    if "sandboxchanged" in event_reasons:
        return "Cluster-level runtime event (pod sandbox rebuilt)"

    if "oomkilled" in event_reasons:
        return "Out of memory — container killed"

    if event_reasons & probe_like and "metric_delta" in types:
        return "Probe failure → pod restart"

    if event_reasons & probe_like and "log_burst" in types:
        return "Probe failure correlated with log burst"

    if event_reasons & deploy_like and len(event_reasons & deploy_like) >= 3:
        return "Pod startup / rolling deployment"

    if "log_burst" in types and len(types) == 1:
        return "Log burst (no accompanying events)"

    if types == {"event"} and event_reasons & deploy_like:
        return "Normal pod lifecycle activity"

    return ""  # let Claude reason over the raw signals


# Formatter 

def format_timeline(service: str, window_start: datetime, window_end: datetime,
                    clusters: list[Cluster], bucket_seconds: int) -> str:
    """Format clusters as Markdown for Claude."""
    if not clusters:
        return (
            f"# Correlation analysis for `{service}`\n"
            f"Window: {window_start.isoformat()} to {window_end.isoformat()}\n\n"
            f"No signals found in this window. The service appears quiet."
        )

    lines = [
        f"# Correlation analysis for `{service}`",
        f"Window: {window_start.isoformat()} to {window_end.isoformat()} "
        f"(bucket: {bucket_seconds}s)",
        f"Clusters: {len(clusters)} · Total signals: {sum(len(c.signals) for c in clusters)}",
        "",
    ]

    for i, cluster in enumerate(clusters, start=1):
        interpretation = interpret_cluster(cluster)
        header = f"## Cluster {i} — {cluster.start.strftime('%H:%M:%S')} UTC"
        if cluster.span_seconds:
            header += f" ({cluster.span_seconds}s span)"
        if interpretation:
            header += f" · {interpretation}"
        lines.append(header)

        for sig in cluster.signals:
            tag = f"[{sig.signal_type}]"
            lines.append(f"- {tag} {sig.summary}")
        lines.append("")

    return "\n".join(lines).strip()