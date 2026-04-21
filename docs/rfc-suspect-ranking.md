# RFC: Suspect Ranking for WatchTower

**Status:** Accepted
**Author:** Aruthra Sathish Kumar
**Date:** 2026-04-20
**Related:** Phase 8, tool `suspect_rank`

## Background

WatchTower captures change events (deploys, config flips, Terraform applies) and
Kubernetes events from observed services. Claude Desktop can query this event
store via the `search_events` and `what_changed` MCP tools.

During real incidents, operators rarely want "every event in the last hour" —
they want **"which change is most likely to have caused this failure?"** A list
of 500 events is noise. A ranked list of 5 suspects is signal.

This RFC describes a scoring algorithm that produces such a ranked list.

## Goal

Given an incident specification `(service, since_timestamp)`, return the top N
change events most likely to have caused the incident, with a score in `[0, 1]`
and a human-readable explanation per suspect.

## Non-goals

- **Not a root cause.** The ranker surfaces candidates. The operator (or Claude)
  still makes the call.
- **Not ML-trained.** Weights are hand-tuned priors, not learned from data. A
  future iteration could train on postmortem outcomes; v1 does not.
- **Not real-time streaming.** Ranking is run on-demand when an operator asks,
  not continuously.

## Design

Each candidate change event receives four signal scores in `[0, 1]`, then a
weighted sum becomes the final score.

### Signal 1: Service match (weight 0.40)

Measures whether the change was to the service that's currently failing.

| Condition                           | Score |
|-------------------------------------|-------|
| `change.service == incident.service`| 1.0   |
| Same K8s namespace                  | 0.3   |
| No match                            | 0.0   |

**Rationale.** An operator's first instinct during a `checkout` failure is to
check what just deployed to `checkout`. This is the highest-weighted signal
because it aligns with operator intuition.

**Limitation.** A change to a service `checkout` depends on (e.g., `currency`)
won't score highly, even though it could be the real cause. Dependency-aware
matching is a future extension and would require a service graph.

### Signal 2: Recency decay (weight 0.25)

Measures how long ago the change happened. Uses exponential decay with a
half-life of 10 minutes:
score = exp(-age_minutes / 10)

| Age       | Score |
|-----------|-------|
| 0 min     | 1.00  |
| 10 min    | 0.50  |
| 20 min    | 0.25  |
| 30 min    | 0.12  |
| 60 min    | 0.02  |

**Rationale.** Incident-response literature and operator intuition agree that
"what happened right before the alert" is heavily weighted. Exponential decay
reflects "recency matters quadratically" better than linear decay.

**Limitation.** A 10-minute half-life is a pragmatic default. Very-slow-to-
manifest incidents (e.g., a memory leak triggered by a deploy 3 hours ago)
will be under-ranked. Operators should be able to widen the half-life when
they suspect a slow-burn cause.

### Signal 3: Blast radius (weight 0.15)

Measures how many other events share the same actor in the same time window.

blast_count = number of events by same actor in the last hour
score = min(1.0, blast_count / 10)

**Rationale.** A deploy by someone who made 10 deploys in the last hour is
probably part of a chaotic release window. Higher blast radius → higher
a-priori probability that something in that batch broke something.

**Limitation.** This is a proxy measure. True blast radius would require
tracking which services each change actually touched. That's Phase 12's
correlation-id work.

### Signal 4: Semantic similarity (weight 0.20)

Measures how textually related the change's title is to the incident
description (or service name, if no description given).

Implementation:

1. Generate sentence embeddings for change titles using the
   `sentence-transformers/all-MiniLM-L6-v2` model (384 dimensions).
2. Store them in the `events.embedding` column (pgvector).
3. At query time, embed the incident description and compute cosine
   similarity via pgvector's `<=>` operator.

score = 1 - cosine_distance(change.embedding, incident.embedding)

**Rationale.** Captures "reads like the failure." A deploy titled "fix payment
flow retry logic" is more suspicious when checkout is broken than a deploy
titled "update CI workflow."

**Limitation.** Only as good as the model. `all-MiniLM-L6-v2` was trained on
general-purpose English; domain-specific terms like `OOMKilled` may not
embed meaningfully. A fine-tuned model on incident corpora would do better;
out of scope for v1.

### Combination
final_score = 0.40 * service_match
+ 0.25 * recency
+ 0.15 * blast_radius
+ 0.20 * semantic_similarity

Weights sum to 1.0, so `final_score ∈ [0, 1]`.

## Weight rationale

Weights were chosen by reasoning about operator intuition:

- **Service match (0.40)** is the single strongest pattern — "the thing that
  broke just had a change" is the most common root cause story.
- **Recency (0.25)** is a strong secondary signal — filters out stale events.
- **Semantic (0.20)** captures domain overlap but has model-quality risk.
- **Blast radius (0.15)** is meaningful but uses a proxy measure, so weighted
  conservatively.

Weights should evolve with telemetry. If postmortems consistently identify
causes the ranker missed, increase the relevant signal. If operators
routinely ignore high-ranked suspects, decrease that signal's weight.

## API

### MCP tool: `suspect_rank`

**Input schema:**

```json
{
  "service": "checkout",
  "since": "10m",
  "incident_description": "Checkout API returning 500s for credit card payments",
  "limit": 5
}
```

- `service` (required): service that is failing
- `since` (optional, default `"30m"`): how far back to look for candidate changes
- `incident_description` (optional): free-form failure description to improve
  semantic match; if omitted, we fall back to the service name
- `limit` (optional, default 5): top-N suspects to return

**Output:** Markdown-formatted ranked list, each suspect including:

- Rank and overall score
- Event title, service, timestamp, actor
- Per-signal score breakdown (so Claude can explain *why* it ranked highly)
- Direct quotes from the payload when relevant (commit SHA, branch, etc.)

## Performance

- Scoring 100 candidates: ~20ms (arithmetic + one similarity query).
- Embedding generation (if backlog): ~50ms per event on CPU.
- First-time query on a service with no embeddings may trigger a batch
  backfill (~5 seconds for 100 events). Subsequent queries hit the cache.

## Testing strategy

- **Unit tests** for each scoring function (exact match logic, decay curve,
  blast radius formula, embedding similarity mock).
- **Integration test** against a seeded event store with known "expected top
  suspect" and assert the ranker finds it.
- **Qualitative test** via Claude Desktop: seed Boutique with known chaos
  (e.g., delete a pod), ask Claude to identify the most likely cause, and
  verify the answer aligns with ground truth.

## Future work

- Dependency-aware service matching (requires service graph from Phase 12
  correlation data).
- Fine-tuned embedding model on postmortem corpora.
- Feedback loop: let operators mark suspects as "helpful" or "irrelevant"
  to auto-tune weights.
- Time-of-day and day-of-week priors (deploys at 5pm on Friday are
  statistically more suspect than deploys at 10am on Tuesday).

## Decision log

| Decision | Reasoning |
|----------|-----------|
| Exponential over linear decay | Matches operator intuition better |
| `all-MiniLM-L6-v2` | CPU-only, 384-dim, battle-tested |
| Weights hand-tuned | v1 has no postmortem data to learn from |
| 10-minute half-life | Typical incident causal window |
| Return markdown output | Claude can cite and reason; pure JSON is opaque |

