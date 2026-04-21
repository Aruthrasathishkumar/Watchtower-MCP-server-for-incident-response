# RFC: Postmortem Generator

**Status:** Accepted
**Author:** Aruthra Sathish Kumar
**Date:** 2026-04-20
**Related:** Phase 17, tool `generate_postmortem`

## Background

Once an incident is resolved, SRE teams write a postmortem. Good
postmortems follow a consistent structure: timeline, impact, root cause,
action items. Writing them is tedious because the data is scattered
across event stores, metric backends, log systems, and chat. Engineers
spend more time assembling facts than analyzing them.

WatchTower already has all the data. This RFC adds a tool that
assembles it into a structured first draft.

## Goal

Given an incident definition (service + time window, or a specific
event id anchor), produce a structured Markdown postmortem draft that
Claude can enrich with narrative and hand to the operator for review.

## Non-goals

- **Not a replacement for human analysis.** The tool provides structure
  and facts, not judgment about why the failure happened.
- **Not a learning loop.** We don't train anything on past incidents.
- **Not published to external systems.** The draft returns to Claude;
  Claude can help the operator publish it wherever.

## Design

### Input

One of:
- `service` + `window_start_iso` + `window_end_iso` (explicit window)
- `service` + `window_minutes` (implicit: ending at the resolve time
  of the most recent resolved PagerDuty incident on that service, or
  now if there's no resolve event)

### What gets collected

For the window:
1. All events from the event store (`search_events`-shaped query)
2. Prometheus restart delta for the service
3. Log bursts detected by the existing `_correlate_helpers`
4. Change events in the 2x-widened window (to catch deploys before the
   incident started)

### What the draft contains

A Markdown document with these sections, pre-filled:

1. **Summary** — window, service, status. One machine-generated sentence.
   Claude rewrites this in prose.
2. **Timeline** — every signal as `HH:MM:SS [source] title`. Sorted
   chronologically.
3. **Impact** — inferred from PagerDuty incident status, pod restart
   count, and error log volume. "Service X was impacted from T1 to T2.
   N container restarts, M log-burst buckets."
4. **Root cause** — empty. Claude fills this based on the timeline and
   the known change events.
5. **Contributing factors** — empty. Claude fills.
6. **Remediation** — lists any `executed` rows from the `approval_audit`
   table in the window. If none, empty with a note.
7. **Action items** — empty. Claude fills.
8. **Lessons learned** — empty. Claude fills.
9. **Appendix: raw signals** — every signal as a bullet list, grouped
   by source system, for the operator to audit.

### Why this split

The tool makes hallucination harder. Everything in the "facts"
sections (timeline, impact, remediation, appendix) is traceable to a
database row. The "interpretation" sections (root cause, contributing
factors, action items, lessons learned) are explicitly left for Claude
to fill, which makes it clear where the AI narrative starts. This
separation is the whole point — an operator reading the postmortem
knows exactly which lines are facts and which are model inference.

## Output format

A single Markdown string. Not stored anywhere. Claude shows it to the
operator, who can copy-paste to Confluence, Notion, GitHub issue, etc.

## Testing strategy

- **Unit tests** for section rendering (known signals → known Markdown).
- **Integration test** — use the 17:25 sandbox event from Phase 7 as
  the test incident. Assert the timeline contains the Unhealthy +
  SandboxChanged + Started sequence.

## Future work

- Markdown templates per team (e.g. one format for product teams,
  another for infra).
- Auto-publish to GitHub Issues or Confluence.
- Attachment of Grafana dashboard screenshots at incident peak.
- Diff-based postmortems: "same incident recurring? here's how it
  differed from last time."

## Decision log

| Decision | Reasoning |
|----------|-----------|
| Structure deterministic, prose by Claude | Hallucination boundary |
| Markdown output | Portable, easy to review |
| No storage | Postmortems are ephemeral drafts; the source data is the record |
| Anchor on PagerDuty resolve event when available | Matches real SRE workflow |