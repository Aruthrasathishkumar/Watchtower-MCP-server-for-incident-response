-- Migration 002: Domain enums for events
--
-- Defining these as enums (rather than free text) prevents typos and
-- documents the valid values at the database level.

-- Event type: what kind of event this is
CREATE TYPE event_type AS ENUM (
    'deploy',
    'terraform_apply',
    'k8s_event',
    'feature_flag',
    'config_change',
    'metric_anomaly',
    'log_burst',
    'trace_error',
    'alert',
    'slack_msg',
    'incident_open',
    'incident_resolved'
);

-- Severity: how bad is this event
CREATE TYPE event_severity AS ENUM (
    'info',
    'warning',
    'error',
    'critical'
);

-- Confirm types created
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'event_type') THEN
        RAISE EXCEPTION 'event_type enum missing';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'event_severity') THEN
        RAISE EXCEPTION 'event_severity enum missing';
    END IF;
    RAISE NOTICE 'Event type enums created successfully';
END $$;