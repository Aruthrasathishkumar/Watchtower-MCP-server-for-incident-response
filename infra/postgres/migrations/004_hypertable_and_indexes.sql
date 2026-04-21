-- Migration 004: Convert to TimescaleDB hypertable and create indexes
--
-- A hypertable is a regular Postgres table that TimescaleDB transparently
-- partitions by time. Queries use normal SQL; partitioning speeds up
-- range scans and data retention.
--
-- chunk_time_interval = 1 day: each underlying partition holds a day
-- of data. Generous for a portfolio project.

SELECT create_hypertable(
    'events',
    by_range('timestamp', INTERVAL '1 day'),
    if_not_exists => TRUE
);

-- Query patterns we index for:
-- 1. Rewind: events for service X between T1 and T2
-- 2. Debug:  latest events for service X
-- 3. Search: events of type Y in the last hour
-- 4. Correlation: events sharing a correlation_id
-- 5. Payload search: events matching a JSON fragment
-- 6. Semantic similarity: events near a given embedding

CREATE INDEX idx_events_service_time
    ON events (service, timestamp DESC)
    WHERE service IS NOT NULL;

CREATE INDEX idx_events_type_time
    ON events (event_type, timestamp DESC);

CREATE INDEX idx_events_correlation
    ON events (correlation_id)
    WHERE correlation_id IS NOT NULL;

CREATE INDEX idx_events_payload
    ON events USING GIN (payload);

CREATE INDEX idx_events_embedding
    ON events USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

DO $$
BEGIN
    RAISE NOTICE 'Hypertable and indexes created successfully';
END $$;