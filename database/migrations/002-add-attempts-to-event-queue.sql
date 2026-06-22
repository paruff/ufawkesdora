-- ============================================================================
-- Migration 002: Add attempts column to event_queue
-- ----------------------------------------------------------------------------
-- The worker uses an attempts counter to track retries for failed event
-- processing. Events are marked as 'error' when attempts >= 3.
-- ============================================================================

-- Add attempts column with default 0 for existing rows
ALTER TABLE event_queue
    ADD COLUMN IF NOT EXISTS attempts SMALLINT NOT NULL DEFAULT 0;

-- Update the status CHECK constraint to include 'processing'
-- (PostgreSQL cannot alter CHECK constraints directly, so we need to
--  drop and recreate the constraint.)
ALTER TABLE event_queue
    DROP CONSTRAINT IF EXISTS event_queue_status_check;

ALTER TABLE event_queue
    ADD CONSTRAINT event_queue_status_check
    CHECK (status IN ('pending', 'processing', 'done', 'error'));

-- Record this migration
INSERT INTO _schema_migrations (version, description, checksum)
VALUES (
    2,
    'Add attempts column to event_queue for worker retry logic',
    'sha256-002-add-attempts-to-event-queue'
)
ON CONFLICT (version) DO NOTHING;
