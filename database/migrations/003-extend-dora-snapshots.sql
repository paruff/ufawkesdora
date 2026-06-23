-- ============================================================================
-- Migration 003: Extend dora_snapshots for Issue 4
-- ----------------------------------------------------------------------------
-- Adds columns needed by compute/metrics.py:
--   fdrt_hours       — Failure Deployment Recovery Time (DORA 2025 reclassification)
--   rework_rate_pct  — user-visible rework as % of total deployments
--   proxy_metrics    — true when lead_time uses PR merge as first_commit proxy
--   dora_tier        — per-metric tier classification (elite/high/medium/low)
-- ============================================================================

-- Add FDRT column (deployment-gap, not incident-resolution gap per DORA 2025)
ALTER TABLE dora_snapshots
    ADD COLUMN IF NOT EXISTS fdrt_hours NUMERIC(10,2);

-- Add rework rate (user-visible reworks / total deployments)
ALTER TABLE dora_snapshots
    ADD COLUMN IF NOT EXISTS rework_rate_pct NUMERIC(5,4)
    CHECK (rework_rate_pct >= 0 AND rework_rate_pct <= 1);

-- Add proxy_metrics flag (true when lead_time uses PR merge as proxy)
ALTER TABLE dora_snapshots
    ADD COLUMN IF NOT EXISTS proxy_metrics BOOLEAN NOT NULL DEFAULT FALSE;

-- Add dora_tier (per-metric tier classification from DORA 2025 thresholds)
ALTER TABLE dora_snapshots
    ADD COLUMN IF NOT EXISTS dora_tier VARCHAR(16)
    CHECK (dora_tier IN ('elite', 'high', 'medium', 'low', 'unknown'));

-- Record this migration
INSERT INTO _schema_migrations (version, description, checksum)
VALUES (
    3,
    'Extend dora_snapshots: fdrt_hours, rework_rate_pct, proxy_metrics, dora_tier',
    'sha256-003-extend-dora-snapshots'
)
ON CONFLICT (version) DO NOTHING;