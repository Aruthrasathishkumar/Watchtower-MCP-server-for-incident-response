# RFC: Signal Correlation for WatchTower

**Status:** Accepted
**Author:** Aruthra Sathish Kumar
**Date:** 2026-04-20
**Related:** Phase 12, tool `correlate_signals`

## Background

WatchTower exposes five single-purpose MCP tools to Claude: `search_events`,
`what_changed`, `suspect_rank`, `query_metrics`, and `search_logs`. Each
answers one kind of question well.

In practice, incident investigation requires combining signals from all of
them on a shared timeline. Today Claude does this by chaining tools and
manually aligning timestamps — it works, but it's slow, error-prone on long
windows, and puts the burden of temporal reasoning on the LLM rather than
on a deterministic backend.

This RFC describes a tool that does the correlation deterministically and
returns a structured, timeline-shaped response to Claude.

## Goal

Given a service and a time window, return a **timeline of correlation
clusters**. Each cluster groups signals that occurred close together in
time and may be causally related. Claude consumes this structure and
generates prose; it does not have to reconstruct the timeline itself.

## Non-goals

- **Not causality detection.** Co-occurrence is not causation. The tool
  surfaces correlation; the operator (or Claude) infers causality.
- **Not anomaly detection.** We use naive heuristics (rate thresholds) to
  find bursts, not ML. A future iteration could learn baselines per service.
- **Not cross-service dependency tracing.** We focus on one service at a
  time. Cross-service correlation is `suspect_rank`'s job and requires
  Phase 12+ correlation-id work.

## Design

### Signal sources

Three categories of signals are gathered:

1. **Events** from the event store (`events` table). All event types
   except metric anomalies (which are a placeholder until Phase 20). This
   covers K8s events, deploys, config changes, etc.

2. **Metric deltas** from Prometheus, specifically restart count
   increments. We query `kube_pod_container_status_restarts_total` at the
   start and end of the window; any delta > 0 is a signal.

3. **Log bursts** from Loki. For each 60-second bucket in the window, we
   count error-level log lines (`severity=~"(?i)(error|warning)"`). A
   bucket is flagged as a burst if its count exceeds `3 × median bucket
   count` in the window, or if it contains a new error string not seen in
   the baseline 15-minute period before the window.

### Clustering

Signals are grouped into clusters by a single rule: **two signals are in
the same cluster if their timestamps are within `bucket_seconds` of each
other** (default 60s). Clusters are chronological and non-overlapping.

This is "temporal co-occurrence" clustering. It's deliberately simple. A
future iteration could add spatial (same-service) clustering for
cross-service cascades.

### Output format

The tool returns Markdown optimized for Claude to narrate. Each cluster
includes:

- Time span and first signal timestamp
- A one-phrase label (e.g., "Pod startup", "Pod churn")
- A list of signals with type tags
- A short interpretation Claude can cite or expand

The interpretation is generated from a small rule set based on which
signal types co-occur:

| Signals present | Interpretation |
|-----------------|----------------|
| deploy + k8s_event(Killing, Scheduled, Started) | "Rolling deployment" |
| k8s_event(Unhealthy) + restart delta + log burst | "Probe failure → restart" |
| k8s_event(SandboxChanged) + restart delta across many services | "Cluster-level runtime event" |
| k8s_event(OOMKilled) + memory spike | "Out of memory" |
| Only k8s_event entries, no app signals | "Normal pod lifecycle" |

If no rule matches, the interpretation is left empty and Claude is free
to reason over the raw signals.

## API

### MCP tool: `correlate_signals`

**Input schema:**

```json

{
"service": "checkoutservice",
"window_start": "2026-04-20T17:00:00Z",
"window_end": "2026-04-20T17:30:00Z",
"bucket_seconds": 60
}

- `service` (required): service to focus on
- `window_start`, `window_end` (optional): ISO timestamps. If omitted,
  defaults to "last 30 minutes"
- `bucket_seconds` (optional, default 60): clustering threshold

**Output:** Markdown timeline as described above.

## Performance

- Event query: single Postgres SELECT, ~5ms.
- Metric query: two Prometheus point queries, ~20ms each.
- Log query: one Loki range query, ~50–200ms.
- Clustering: O(N log N) in Python, negligible.
- **Total per call:** ~100–300ms for a 30-minute window.

## Testing strategy

- **Unit tests** for the bucket-clustering logic (known input → known
  clusters).
- **Unit tests** for the interpretation rule set.
- **Integration test** against a seeded event store + recorded Loki
  fixtures: simulate the Boutique 17:25 sandbox event, assert the tool
  identifies it as "Cluster-level runtime event."

## Future work

- Per-service baseline learning for log burst thresholds.
- Cross-service clustering using `correlation_id` (Phase 12+ work).
- A "silence" signal: flag unexpected absence of expected logs.
- PagerDuty integration: auto-trigger `correlate_signals` when an alert
  fires and attach the timeline to the incident.

  