-- Migration 005: Table and column documentation
--
-- Adds human-readable comments to the events table and its columns.
-- These appear in \d output in psql and in tools like pgAdmin, dbeaver, etc.

COMMENT ON TABLE events IS
    'Unified event store. All change events, observability signals, and collaboration data flow into this table.';

COMMENT ON COLUMN events.timestamp IS
    'When the event actually happened (UTC).';

COMMENT ON COLUMN events.ingested_at IS
    'When WatchTower ingested the event. (ingested_at - timestamp) = ingestion lag.';

COMMENT ON COLUMN events.event_type IS
    'What kind of event this is. See event_type enum.';

COMMENT ON COLUMN events.severity IS
    'How bad this event is. See event_severity enum.';

COMMENT ON COLUMN events.service IS
    'Service name this event relates to. NULL for cluster-wide events.';

COMMENT ON COLUMN events.actor IS
    'User or system that caused this event. NULL if unknown.';

COMMENT ON COLUMN events.source_system IS
    'Which system emitted the event (github, prometheus, k8s_api, slack, etc.).';

COMMENT ON COLUMN events.source_id IS
    'Original ID in the source system. Used with source_system for dedup.';

COMMENT ON COLUMN events.title IS
    'Human-readable one-line description of the event.';

COMMENT ON COLUMN events.payload IS
    'Full source-specific data in JSONB. Queryable via @> and JSON path ops.';

COMMENT ON COLUMN events.correlation_id IS
    'Groups related events. Populated asynchronously by the correlation engine.';

COMMENT ON COLUMN events.embedding IS
    'Semantic embedding of title + payload summary. 384 dims matches MiniLM.';