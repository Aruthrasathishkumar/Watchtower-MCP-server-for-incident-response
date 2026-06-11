# 🛡️ WatchTower - An MCP server for end-to-end incident response

**An AI-native incident response platform where Claude Desktop orchestrates investigation, diagnosis, and safe remediation across real production signals - GitHub, Kubernetes, Prometheus, Loki, Slack, and PagerDuty - through a unified MCP (Model Context Protocol) server.**

Live Demo (Frontend Preview):
https://aruthrasathishkumar.github.io/Watchtower-MCP-server-for-incident-response/

> **Note:** The hosted page is a read-only UI backed by static snapshots of a real WatchTower event store. The MCP server, Postgres, and observability stack run locally by design - a deliberate choice so tool execution, approvals, and remediations stay under operator control. See [Running locally](#running-locally) to run the full system.

## What it does

WatchTower exposes 12 MCP tools that let Claude Desktop:

1. **Investigate** - search events, query Prometheus metrics, search Loki logs, correlate signals across sources
2. **Diagnose** - rank suspect services using a 4-signal scoring algorithm (service match, recency decay, actor blast radius, pgvector semantic similarity)
3. **Act** - propose remediations from YAML runbooks, request human approval via HMAC-signed tokens, execute approved actions safely
4. **Document** - generate publish-ready postmortems with deterministic facts and Claude-authored narrative

The full incident-response loop - detection, investigation, safe remediation, postmortem - runnable locally on minikube against Google's Online Boutique demo.

## Architecture

<img src="./watchtower system architecture.png" width="800"/>

**How it works.** Claude Desktop connects to the WatchTower MCP server over stdio. The server exposes 12 tools that let Claude query a unified Postgres event store (fed by four collectors), run PromQL against Prometheus and LogQL against Loki, rank suspect services, and propose remediations from YAML runbooks. Remediations execute only when the operator returns a valid HMAC-signed approval token - enforcing human-in-the-loop safety with a full audit trail.

## Tech stack

- **Server:** Python 3.12, MCP SDK, psycopg3
- **Storage:** Postgres 16 + TimescaleDB + pgvector (embeddings via `sentence-transformers`, 384-dim)
- **Observability:** Prometheus (kube-prometheus-stack), Loki + Promtail
- **Orchestration:** minikube + Helm, Google Online Boutique demo app
- **Integrations:** PyGithub, Kubernetes Python client, `slack-sdk`, PagerDuty REST API
- **Security:** HMAC-SHA256 with `hmac.compare_digest`, single-use nonces, append-only audit log
- **IaC:** Terraform (`kreuzwerker/docker`, `hashicorp/kubernetes`, `hashicorp/helm` providers)
- **Testing:** pytest (35 tests, ~0.3s runtime)
- **Frontend:** Vanilla HTML/CSS/JS, deployed via GitHub Pages

## The 12 MCP tools

| Category      | Tool                       | Purpose                                               |
|---------------|----------------------------|-------------------------------------------------------|
| Investigation | `search_events`            | Full-text + filtered query across the event store     |
| Investigation | `what_changed`             | Change triage for a service + time window             |
| Investigation | `query_metrics`            | Execute PromQL against Prometheus                     |
| Investigation | `search_logs`              | LogQL query against Loki                              |
| Investigation | `correlate_signals`        | Cluster events, metric deltas, log bursts by service  |
| Diagnosis     | `suspect_rank`             | 4-signal weighted ranking of candidate services       |
| Runbooks      | `list_applicable_runbooks` | Match runbooks to current signals                     |
| Runbooks      | `execute_runbook_checks`   | Run read-only preflight checks                        |
| Runbooks      | `propose_remedy`           | Present remedy options with safety classifications    |
| Approval      | `request_approval`         | Raise an approval request with rationale              |
| Approval      | `execute_approved_remedy`  | Execute only with valid HMAC token (replay-protected) |
| Documentation | `generate_postmortem`      | Deterministic facts + Claude-authored interpretation  |


## Security model

The approval broker implements human-in-the-loop safety:

- **HMAC-SHA256 signed tokens** bind proposal-id + runbook-id + remedy-id + approver + timestamp
- **5-minute TTL** with explicit `expires_at` field
- **Single-use nonces** recorded in an audit table to prevent replay attacks
- **Runbook re-parsed at execution** to prevent time-of-check-vs-time-of-use issues
- **Subprocess hardening** - `shlex.split`, no shell, 30-second timeout, 50KB output cap, refuses `<PLACEHOLDER>` commands
- **Append-only audit log** - every approval attempt, execution, replay, and expiry recorded with actor

See `docs/rfc-security-model.md` for the full threat model and decision log.


## RFCs

Design decisions documented as RFCs with problem statements, alternatives considered, and decision logs:

- `rfc-suspect-ranking.md` - weight tuning for the 4-signal scorer
- `rfc-correlate-signals.md` - clustering algorithm + interpretation rules
- `rfc-runbook-engine.md` - YAML schema + check/remedy/trigger contracts
- `rfc-security-model.md` - HMAC token shape, threat model, 5 verification boundaries
- `rfc-postmortem-generator.md` - fact/interpretation split, 9-section structure



## Running locally

Prerequisites: Docker, minikube, kubectl, Python 3.12, Claude Desktop.

```bash
# Bring up Postgres
./scripts/up.sh

# Bring up minikube + Boutique + Prometheus + Loki
./scripts/k8s-up.sh

# Install the server
cd server && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in tokens

# Run tests
pytest   # 35 passed in 0.3s

# Start the MCP server
python -m watchtower.server
```

Then register WatchTower in Claude Desktop's `claude_desktop_config.json` and restart. The 12 tools appear in the MCP panel.


## Frontend (GitHub Pages)

A vanilla HTML/CSS/JS frontend displays the event store, incident details, and approval audit log using static JSON snapshots exported from Postgres:

```bash
python scripts/export_frontend_data.py   # regenerate snapshots
cd frontend/public && python3 -m http.server 8080
```

No build step. Three views: timeline (stat cards + filters), incident detail (event + ±30min related signals), approvals (requests + HMAC audit log).


## Infrastructure as Code

Terraform module under `infra/terraform/` declares the full stack - Postgres container, three Kubernetes namespaces, Prometheus + Loki + Promtail Helm releases - across 8 HCL files with version pinning and 5 outputs. `terraform init` and `terraform plan` are verified clean; `terraform apply` against the live demo stack is intentionally not run (collision with imperatively bootstrapped resources - documented in `infra/terraform/README.md`).


## What's intentionally not included

- **Tempo distributed tracing** - the Boutique minimal release lacks OpenTelemetry instrumentation
- **Production cloud deployment** - this is a local demo; cloud IaC would be a future phase
- **Live backend for the frontend** - static JSON snapshots are a deliberate simplicity choice
