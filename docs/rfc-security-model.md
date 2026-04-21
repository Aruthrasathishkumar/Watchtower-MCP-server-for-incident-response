# RFC: WatchTower Security Model

**Status:** Accepted
**Author:** Aruthra Sathish Kumar
**Date:** 2026-04-20
**Related:** Phase 14, Approval Broker

## Background

Phases 1–13 built WatchTower's read-only surface: ingest, observe, analyze,
propose. Phase 14 adds the first mutating capability — the ability to
execute remedies (kubectl commands, scripts, HTTP calls). Any mutating
capability must be gated by explicit human consent, bound to a specific
action, time-limited, and auditable.

This RFC documents the security model for that gating.

## Threat model

### Assets protected
- **Operator consent** — the "yes" or "no" a human says to a proposed remedy.
- **Infrastructure state** — Boutique pods, deployments, configs.
- **Audit trail** — the record of who did what, when, and why.

### Adversaries considered
- **Malicious or buggy MCP client.** Claude, a future Claude variant, a
  third-party MCP client, or a bug in any of them could issue requests
  WatchTower treats as approved when they aren't.
- **Unauthorized process on the host.** Another process running as the
  same OS user could read files or call WatchTower endpoints.
- **Replay attacker.** Anyone who captures an approval token and tries to
  reuse it after the remedy has already executed.
- **Clock skew attacker.** Anyone manipulating system time to extend token
  TTL.

### Adversaries NOT considered
- **Attacker with root on the host.** Out of scope. If they can read the
  HMAC key from `.env`, they can forge tokens. We rely on filesystem
  permissions.
- **Network attacker.** WatchTower runs locally; all traffic is loopback.
  Production deployment would need TLS + mTLS.
- **Attacker who compromised the audit log database.** Immutable logging
  requires write-only database credentials or append-only storage; v1
  uses the same Postgres connection as everything else.

## Design

### Token shape

An approval token is a base64-urlsafe string of the form:

    <payload_b64>.<signature_b64>

Where `payload_b64` is a JSON object:

```json
{
"v": 1,
"pid": "<proposal_id>",
"rid": "<remedy_id>",
"rb": "<runbook_id>",
"approver": "<free-form operator identifier>",
"iat": 1729534800,     // issued at (unix seconds)
"exp": 1729535100,     // expires at (unix seconds)
"nonce": "<random 16 bytes hex>"
}

And `signature_b64` is HMAC-SHA256 over `payload_b64` using the server's
secret key `WATCHTOWER_APPROVAL_SECRET`.

### Lifecycle

1. Claude calls `request_approval(runbook_id, remedy_id, rationale)`.
   WatchTower creates an `approval_requests` row with status `pending`
   and returns a `proposal_id`.
2. The operator runs `python -m watchtower.cli.approve <proposal_id>`
   at the terminal. The CLI loads the pending request, shows the full
   proposal, asks for confirmation. On yes, it generates a token and
   writes it to stdout.
3. The operator pastes the token back into the Claude conversation.
4. Claude calls `execute_approved_remedy(token)`. WatchTower verifies
   the signature, checks the expiry, checks that the token hasn't been
   used before (by nonce), runs the command, and records the result
   in `approval_audit`.

### Boundary checks on execution

Every token passed to `execute_approved_remedy` must pass ALL of:

1. **Signature valid** — HMAC matches with the current secret.
2. **Not expired** — `now < exp`.
3. **Not already used** — `nonce` not present in `approval_audit`.
4. **Matches a known approval request** — `pid` exists in
   `approval_requests`.
5. **Runbook + remedy still exists** — re-parse the runbook; the remedy
   id must still be present. Prevents running a command from a runbook
   that's been deleted or rewritten since approval.

If any check fails, the tool returns a specific error AND writes a
failed-attempt row to `approval_audit` for forensic review.

### What the executor may do

Only the exact command string from the runbook's remedy. No variable
substitution, no shell interpolation beyond what the subprocess runner
requires, no environment variable overrides.

`subprocess.run(shlex.split(cmd), capture_output=True, timeout=30)`.

If `cmd` is empty (a "manual remedy" in the runbook sense), the executor
records the approval but does nothing — a no-op success.

## Audit log

Two tables:

**`approval_requests`** — records every proposal
- id (uuid, PK)
- runbook_id, remedy_id (strings)
- rationale (text) — what Claude said
- requested_at (timestamptz)
- status (enum: pending, approved, denied, expired, executed)

**`approval_audit`** — append-only log of every attempt
- id (uuid, PK)
- proposal_id (fk)
- action (enum: requested, approved, denied, executed, execution_failed,
  invalid_token, replay_attempt)
- actor (text) — CLI operator name or `claude`
- token_nonce (text, nullable) — for replay detection
- token_payload (jsonb, nullable) — full decoded payload
- stdout, stderr (text) — for executed rows
- exit_code (int, nullable)
- at (timestamptz, default now())

Neither table has an UPDATE path in the application code. Rows are only
inserted.

## What an interviewer might ask

- *"Why HMAC and not RSA?"* HMAC-SHA256 is correct for symmetric trust
  between two processes running on the same machine (broker + executor
  are the same process in v1). RSA would be over-engineering and slower.
  A production multi-node deployment would switch to asymmetric signing.

- *"What if the operator's terminal is compromised?"* We're out of the
  threat model. If the attacker has the operator's shell, they can
  approve anything the operator could. The audit log still records
  the approval with the operator's identity, which is the best we can do.

- *"Why 5-minute TTL?"* Balance between "short enough that a leaked
  token is nearly useless" and "long enough that the operator doesn't
  race the clock to paste the token back." Tunable via
  `WATCHTOWER_APPROVAL_TTL_SECONDS`.

- *"Why not require a second factor?"* This is a dev-local prototype.
  In production, I'd require WebAuthn or a hardware key on the approval
  step. For v1, the operator's ability to run a CLI command on the host
  IS the second factor.

## Future work

- Move `WATCHTOWER_APPROVAL_SECRET` to a proper secret manager (e.g.
  HashiCorp Vault) rather than `.env`.
- Add a web UI for approvals (Phase 18) with session-bound tokens.
- Add rate limiting on approval requests to prevent Claude from spamming
  the operator with proposals.
- Integrate with real identity (GitHub OAuth, SSO) so the `approver`
  field is verifiable rather than free-form.

## Decision log

| Decision | Reasoning |
|----------|-----------|
| HMAC over RSA | Symmetric trust, same-process verification |
| 5-minute TTL | Prototype-appropriate balance |
| Single-use tokens | Prevents replay within the TTL window |
| Re-parse runbook at execution | Prevents race between approval and runbook edits |
| Audit log on same Postgres | Simplicity; production woul