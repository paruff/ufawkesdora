-- ============================================================================
-- 02-dora-roles.sql
-- ----------------------------------------------------------------------------
-- Creates the dora_app role with least-privilege table-level grants.
-- NO superuser. NO schema ownership.
-- Idempotent — safe to re-run.
-- ============================================================================

\c dora_metrics

-- ============================================================================
-- dora_app role (create if not exists)
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dora_app') THEN
        CREATE ROLE dora_app WITH LOGIN PASSWORD 'change_me_in_production';  -- pragma: allowlist secret
        RAISE NOTICE 'Created role: dora_app';
    ELSE
        RAISE NOTICE 'Role already exists: dora_app';
    END IF;
END
$$;

-- ============================================================================
-- Revoke any pre-existing superuser / ownership grants (defense in depth)
-- ============================================================================
ALTER ROLE dora_app WITH NOSUPERUSER NOCREATEDB NOCREATEROLE;

-- ============================================================================
-- Grant schema usage (but NOT ownership)
-- ============================================================================
GRANT USAGE ON SCHEMA public TO dora_app;

-- ============================================================================
-- Table-level grants (least privilege)
-- ============================================================================

-- event_queue: only INSERT (event producers write, consumers read via app)
GRANT INSERT ON TABLE event_queue TO dora_app;

-- raw_events: SELECT (read for computation) + INSERT (write processed events)
GRANT SELECT, INSERT ON TABLE raw_events TO dora_app;

-- dora_snapshots: SELECT (read for analysis) + INSERT (write computed metrics)
GRANT SELECT, INSERT ON TABLE dora_snapshots TO dora_app;

-- archetype_history: read-only
GRANT SELECT ON TABLE archetype_history TO dora_app;

-- wellbeing_surveys: read-only
GRANT SELECT ON TABLE wellbeing_surveys TO dora_app;

-- vsi_stage_breakdown: read-only
GRANT SELECT ON TABLE vsi_stage_breakdown TO dora_app;

-- ============================================================================
-- Sequence grants (needed for INSERT to auto-increment)
-- ============================================================================
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO dora_app;

-- ============================================================================
-- Default privileges for future tables created by the schema owner
-- ============================================================================
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT ON TABLES TO dora_app;

-- ============================================================================
-- Verification (runs only if dora_app exists)
-- ============================================================================
DO $$
DECLARE
    role_super bool;
BEGIN
    SELECT rolsuper INTO role_super FROM pg_roles WHERE rolname = 'dora_app';
    IF role_super THEN
        RAISE WARNING 'dora_app has superuser privileges — this violates least-privilege policy';
    ELSE
        RAISE NOTICE 'dora_app role verified: NOT superuser — OK';
    END IF;
END
$$;
