-- Migration 006: Approval Broker tables.
-- Tracks proposed remedies, approvals, and executions for audit.

BEGIN;

-- Create approval_status enum for the request lifecycle
DO $$ BEGIN
    CREATE TYPE approval_status AS ENUM (
        'pending',
        'approved',
        'denied',
        'expired',
        'executed'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Create audit_action enum for the append-only audit log
DO $$ BEGIN
    CREATE TYPE audit_action AS ENUM (
        'requested',
        'approved',
        'denied',
        'executed',
        'execution_failed',
        'invalid_token',
        'replay_attempt',
        'expired_token'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


CREATE TABLE IF NOT EXISTS approval_requests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    runbook_id    TEXT NOT NULL,
    remedy_id     TEXT NOT NULL,
    rationale     TEXT,
    requested_by  TEXT NOT NULL DEFAULT 'claude',
    requested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status        approval_status NOT NULL DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS approval_requests_status_idx
    ON approval_requests (status, requested_at DESC);


CREATE TABLE IF NOT EXISTS approval_audit (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id     UUID REFERENCES approval_requests(id),
    action          audit_action NOT NULL,
    actor           TEXT NOT NULL,
    token_nonce     TEXT,
    token_payload   JSONB,
    stdout          TEXT,
    stderr          TEXT,
    exit_code       INTEGER,
    at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS approval_audit_proposal_idx
    ON approval_audit (proposal_id, at DESC);

CREATE INDEX IF NOT EXISTS approval_audit_nonce_idx
    ON approval_audit (token_nonce)
    WHERE token_nonce IS NOT NULL;

COMMIT;