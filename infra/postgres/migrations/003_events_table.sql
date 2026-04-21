-- Migration 003: Core events table
--
-- The unified event store. Every change event, observability signal, and
-- collaboration artifact is recorded here.
--
-- Design notes:
-- - (timestamp, id) is the composite primary key because TimescaleDB
--   requires the partitioning column to be in the primary key.
-- - (source_system, source_id, timestamp) is a unique constraint so
--   collectors can safely retry without creating duplicates.
-- - payload is JSONB so different event sources can store different
--   fields without schema changes.
-- - embedding is nullable; it is computed asynchronously by a background
--   job, not at insert time.
-- - correlation_id is nullable and populated later by the correlation
--   engine that groups related events.

CREATE TABLE events (
    id              UUID NOT NULL DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    event_type      event_type NOT NULL,
    severity        event_severity NOT NULL DEFAULT 'info',

    service         TEXT,
    actor           TEXT,

    source_system   TEXT NOT NULL,
    source_id       TEXT NOT NULL,

    title           TEXT NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,

    correlation_id  UUID,
    embedding       VECTOR(384),

    PRIMARY KEY (timestamp, id),
    UNIQUE (source_system, source_id, timestamp)
);