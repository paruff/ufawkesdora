-- ============================================================================
-- 01-dora-schema.sql
-- ----------------------------------------------------------------------------
-- Creates all uFawkesDORA tables in the dora_metrics database.
-- Idempotent — all CREATE statements use IF NOT EXISTS.
-- ============================================================================

-- Connect to the target database
\c dora_metrics

-- ============================================================================
-- event_queue — incoming event buffer
-- ============================================================================
CREATE TABLE IF NOT EXISTS event_queue (
    id              BIGSERIAL       PRIMARY KEY,
    event_type      VARCHAR(64)     NOT NULL,
    source          VARCHAR(128)    NOT NULL,
    payload         JSONB           NOT NULL,
    status          VARCHAR(32)     NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'processing', 'done', 'error')),
    attempts        SMALLINT        NOT NULL DEFAULT 0,
    received_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_event_queue_status_received
    ON event_queue (status, received_at);

-- ============================================================================
-- raw_events — processed deployment/CI events (will become hypertable)
-- ============================================================================
CREATE TABLE IF NOT EXISTS raw_events (
    id              BIGSERIAL       NOT NULL,
    event_queue_id  BIGINT          REFERENCES event_queue(id),
    event_type      VARCHAR(64)     NOT NULL,
    source          VARCHAR(128)    NOT NULL,
    outcome         VARCHAR(32)     NOT NULL
                                    CHECK (outcome IN ('success', 'failure', 'rollback', 'unknown')),
    duration_seconds INTEGER,
    metadata        JSONB,
    recorded_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    ingested_at     TIMESTAMPTZ     DEFAULT NOW(),
    -- Composite PK includes recorded_at for TimescaleDB hypertable partitioning
    PRIMARY KEY (recorded_at, id)
);

CREATE INDEX IF NOT EXISTS idx_raw_events_recorded_at
    ON raw_events (recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_events_type_outcome
    ON raw_events (event_type, outcome);

-- ============================================================================
-- dora_snapshots — periodic DORA metric snapshots (will become hypertable)
-- ============================================================================
CREATE TABLE IF NOT EXISTS dora_snapshots (
    id              BIGSERIAL       NOT NULL,
    team_id                 VARCHAR(64)     NOT NULL,
    deployment_frequency    NUMERIC(10,4)   NOT NULL,
    lead_time_hours         NUMERIC(10,2),
    change_failure_rate     NUMERIC(5,4)
                            CHECK (change_failure_rate >= 0 AND change_failure_rate <= 1),
    time_to_restore_hours   NUMERIC(10,2),
    snapshot_window_start   TIMESTAMPTZ     NOT NULL,
    snapshot_window_end     TIMESTAMPTZ     NOT NULL,
    recorded_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_window CHECK (snapshot_window_end > snapshot_window_start),
    -- Composite PK includes recorded_at for TimescaleDB hypertable partitioning
    PRIMARY KEY (recorded_at, id)
);

CREATE INDEX IF NOT EXISTS idx_dora_snapshots_team_recorded
    ON dora_snapshots (team_id, recorded_at DESC);

-- ============================================================================
-- archetype_history — team archetype classifications over time
-- ============================================================================
CREATE TABLE IF NOT EXISTS archetype_history (
    id              BIGSERIAL       PRIMARY KEY,
    team_id         VARCHAR(64)     NOT NULL,
    archetype       VARCHAR(32)     NOT NULL
                    CHECK (archetype IN ('elite', 'high', 'medium', 'low', 'unknown')),
    snapshot_id     BIGINT,  -- FK enforced at application level (TimescaleDB constraint limitation)
    confidence      NUMERIC(3,2)
                    CHECK (confidence >= 0 AND confidence <= 1),
    recorded_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_archetype_team_recorded
    ON archetype_history (team_id, recorded_at DESC);

-- ============================================================================
-- wellbeing_surveys — developer wellbeing survey responses
-- ============================================================================
CREATE TABLE IF NOT EXISTS wellbeing_surveys (
    id              BIGSERIAL       PRIMARY KEY,
    respondent_id   VARCHAR(128)    NOT NULL,
    survey_version  VARCHAR(16)     NOT NULL,
    q1_score        SMALLINT        NOT NULL CHECK (q1_score BETWEEN 1 AND 5),
    q2_score        SMALLINT        NOT NULL CHECK (q2_score BETWEEN 1 AND 5),
    q3_score        SMALLINT        NOT NULL CHECK (q3_score BETWEEN 1 AND 5),
    q4_score        SMALLINT        NOT NULL CHECK (q4_score BETWEEN 1 AND 5),
    q5_score        SMALLINT        NOT NULL CHECK (q5_score BETWEEN 1 AND 5),
    free_text       TEXT,
    submitted_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wellbeing_survey_version
    ON wellbeing_surveys (survey_version, submitted_at);

-- ============================================================================
-- vsi_stage_breakdown — value stream stage timing data (will become hypertable)
-- ============================================================================
CREATE TABLE IF NOT EXISTS vsi_stage_breakdown (
    id                  BIGSERIAL       NOT NULL,
    deployment_id       VARCHAR(128)    NOT NULL,
    stage_name          VARCHAR(64)     NOT NULL,
    duration_seconds    INTEGER         NOT NULL CHECK (duration_seconds >= 0),
    status              VARCHAR(32)     NOT NULL
                        CHECK (status IN ('success', 'failure', 'skipped', 'pending')),
    metadata            JSONB,
    recorded_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    -- Composite PK includes recorded_at for TimescaleDB hypertable partitioning
    PRIMARY KEY (recorded_at, id)
);

CREATE INDEX IF NOT EXISTS idx_vsi_deployment_stage
    ON vsi_stage_breakdown (deployment_id, stage_name);

CREATE INDEX IF NOT EXISTS idx_vsi_recorded_at
    ON vsi_stage_breakdown (recorded_at DESC);
