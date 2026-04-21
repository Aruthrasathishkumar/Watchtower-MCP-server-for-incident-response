-- Migration 001: Enable required PostgreSQL extensions
--
-- TimescaleDB: time-series capabilities (hypertables, continuous aggregates)
-- pgvector:    vector data type and similarity search for embeddings
-- pgcrypto:    gen_random_uuid() function for UUID primary keys

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Verify extensions installed successfully
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        RAISE EXCEPTION 'timescaledb extension failed to load';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'vector extension failed to load';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto') THEN
        RAISE EXCEPTION 'pgcrypto extension failed to load';
    END IF;
    RAISE NOTICE 'All extensions enabled successfully';
END $$;