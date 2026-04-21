# RFC: Runbook Engine

**Status:** Accepted
**Author:** Aruthra Sathish Kumar
**Date:** 2026-04-20
**Related:** Phase 13, tools `list_applicable_runbooks`,
  `execute_runbook_checks`, `propose_remedy`

## Background

Real SRE teams maintain runbooks — text documents describing "when X
happens, do Y." They typically live in wikis, are out-of-date by the
third incident, and are rarely consulted during pages because reading
prose under stress is slow.

WatchTower's bet: if runbooks are **machine-readable**, Claude can
retrieve and execute them during incident response. The operator sees
structured proposals, not prose to skim.

## Goal

Define a YAML runbook schema, a loader, and three MCP tools so that
Claude can:

1. Match runbooks to ongoing incidents (via triggers)
2. Execute runbook checks (read-only diagnostics)
3. Propose runbook remedies (mutating actions, deferred to Phase 14
   for execution)

## Non-goals

- **Not a workflow engine.** Runbooks are flat: checks run in parallel,
  remedies are shown one-at-a-time. No loops, no conditionals beyond
  trigger matching.
- **Not execution of mutating operations (yet).** Phase 13 implements
  `propose_remedy` as a planning step only. The Approval Broker
  (Phase 14) adds HMAC-signed consent tokens and the actual executor.
- **Not authored-by-AI runbooks.** Runbooks are hand-written YAML files
  committed to the repo. A future iteration could generate runbooks
  from postmortems.

## Design

### Runbook schema

```yaml
id: <short unique string>              # e.g. "checkout-latency"
description: <one-sentence summary>
version: 1                              # schema version

triggers:
  - signal: <log_burst|high_latency|pod_restart|service_down>
    service: <service name>
    threshold: <optional number>

checks:
  - id: <check id>
    description: <one-liner>
    type: prometheus | loki | shell
    query: <PromQL or LogQL expression, or shell command>
    window: <e.g. "10m", optional>

remedies:
  - id: <remedy id>
    description: <one-liner>
    requires_approval: true             # always true in v1
    command: <shell command or kubectl>
    safety: disruptive | read_only | unknown
```

### Execution model

- **Checks** run automatically when `execute_runbook_checks` is called.
  Only `prometheus` and `loki` check types are supported in Phase 13;
  `shell` checks return an error telling the caller to wait for Phase 14.
- **Remedies** do NOT execute in Phase 13. `propose_remedy` returns a
  proposal object describing what would be done, but no command runs.

### Trigger matching

`list_applicable_runbooks(service, signals)` returns runbooks whose
triggers match the provided service AND at least one of the provided
signals. Signal matching is type-based (the signal names in the trigger
spec), not value-based — threshold evaluation is the caller's job.

### Safety properties

1. Check executor is read-only. Even if a hostile runbook file contained
   a `shell` check, the executor refuses to run it.
2. Remedies return proposals, not executions. The audit trail is
   Claude's narration + the proposal JSON.
3. Runbooks are loaded from a single trusted directory (`runbooks/`).
   No runtime upload, no API that accepts runbook YAML.

## Future work (Phase 14 and beyond)

- HMAC-signed approval tokens with short TTLs
- Actual command executor that checks the signed token before running
- Structured audit log of every approval + execution
- Runbook matching on metric thresholds, not just signal presence
- Runbook suggestion from incident retrospectives

## Decision log

| Decision | Reasoning |
|----------|-----------|
| YAML schema over Python DSL | Human-writable, reviewable in PRs |
| Read-only check types only in v1 | Security: can't be bypassed by runbook authorship |
| Propose-but-don't-execute remedies | Forces the HITL gap to be real |
| Three separate MCP tools (not one) | Each is a distinct reasoning step |