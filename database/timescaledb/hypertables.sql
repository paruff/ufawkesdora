-- ============================================================================
-- hypertables.sql
-- ----------------------------------------------------------------------------
-- Converts time-series tables to TimescaleDB hypertables.
-- Idempotent — skips conversion if already a hypertable.
--
-- Requires: timescaledb extension to be installed (loaded via shared_preload_libraries)
-- Run AFTER 01-dora-schema.sql and before any data insertion.
-- ============================================================================

\c dora_metrics

-- ============================================================================
-- Ensure TimescaleDB extension is installed
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================================
-- Helper: create hypertable if not already one
-- ============================================================================
DO $$
DECLARE
    is_hypertable boolean;
BEGIN
    -- Check if raw_events is already a hypertable
    SELECT COUNT(*) > 0 INTO is_hypertable
    FROM timescaledb_information.hypertables
    WHERE hypertable_name = 'raw_events' AND hypertable_schema = 'public';

    IF NOT is_hypertable THEN
        PERFORM create_hypertable('raw_events', 'recorded_at',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        );
        RAISE NOTICE 'Converted raw_events to hypertable (1-day chunks)';
    ELSE
        RAISE NOTICE 'raw_events is already a hypertable — skipping';
    END IF;
END
$$;

DO $$
DECLARE
    is_hypertable boolean;
BEGIN
    SELECT COUNT(*) > 0 INTO is_hypertable
    FROM timescaledb_information.hypertables
    WHERE hypertable_name = 'dora_snapshots' AND hypertable_schema = 'public';

    IF NOT is_hypertable THEN
        PERFORM create_hypertable('dora_snapshots', 'recorded_at',
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE
        );
        RAISE NOTICE 'Converted dora_snapshots to hypertable (7-day chunks)';
    ELSE
        RAISE NOTICE 'dora_snapshots is already a hypertable — skipping';
    END IF;
END
$$;

DO $$
DECLARE
    is_hypertable boolean;
BEGIN
    SELECT COUNT(*) > 0 INTO is_hypertable
    FROM timescaledb_information.hypertables
    WHERE hypertable_name = 'vsi_stage_breakdown' AND hypertable_schema = 'public';

    IF NOT is_hypertable THEN
        PERFORM create_hypertable('vsi_stage_breakdown', 'recorded_at',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        );
        RAISE NOTICE 'Converted vsi_stage_breakdown to hypertable (1-day chunks)';
    ELSE
        RAISE NOTICE 'vsi_stage_breakdown is already a hypertable — skipping';
    END IF;
END
$$;

-- ============================================================================
-- Enable compression policy on hypertables (after 7 days)
-- ============================================================================
ALTER TABLE raw_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'event_type',
    timescaledb.compress_orderby = 'recorded_at DESC'
);

ALTER TABLE dora_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'team_id',
    timescaledb.compress_orderby = 'recorded_at DESC'
);

ALTER TABLE vsi_stage_breakdown SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'stage_name',
    timescaledb.compress_orderby = 'recorded_at DESC'
);

SELECT add_compression_policy('raw_events', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('dora_snapshots', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('vsi_stage_breakdown', INTERVAL '7 days', if_not_exists => TRUE);
