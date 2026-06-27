# Review Report — Issue 15: Value Stream Indicators

**Result: APPROVED** ✅

## Review Checks

### 1. Correctness — PASS ✅
- `compute/vsi.py` correctly implements all 6 acceptance criteria from ISSUE-015
- Stage durations match spec §7 definitions:
  - Coding: `first_commit_at → opened_at` ✓
  - Review: `opened_at → merged_at` ✓
  - Deploy: `merged_at → nearest deployment` ✓
  - CI: skipped for v0.1 (per spec) ✓
- VSM efficiency = value-add / total × 100 ✓
- Bottleneck = highest median stage ✓

### 2. Scope — PASS ✅
- Only 3 new files created:
  - `compute/vsi.py` (required by AC-01)
  - `dashboards/value-stream.json` (required by AC-05)
  - `tests/unit/test_vsi.py` (required by AC-06)
- No existing files modified
- No scope creep

### 3. Design Compliance — PASS ✅
- Follows two-plane architecture: stateless compute, reads/writes PostgreSQL
- Writes to `vsi_stage_breakdown` table (defined in `database/init/01-dora-schema.sql`)
- Column names match schema: `deployment_id`, `stage_name`, `duration_seconds`, `status`, `metadata`
- Follows same patterns as `compute/metrics.py`:
  - `VSIDB` class mirrors `MetricsDB` (async context manager, pool pattern)
  - CLI with `--window`, `--team`, `--pushgateway`, `--verbose`, `--json` flags
  - Pushgateway integration for Prometheus metrics
  - Same logging style and entrypoint pattern

### 4. Maintainability — PASS ✅
- Clear class/method structure following established patterns
- Inline documentation and type annotations throughout
- All 30 unit tests pass with comprehensive coverage
- CLI supports JSON output for programmatic consumption

### 5. Risk — PASS ✅ (Low risk)
- **Security**: No secrets exposed. Database credentials from env vars (same pattern as metrics.py)
- **Performance**: Queries use indexed columns (`recorded_at`, `event_type`, `source`, `metadata->status`)
- **Breaking changes**: No existing files modified — zero regression risk
- **CI stage deferred**: Documented in dashboard and code comments

### 6. Acceptance Criteria Coverage — ALL PASS ✅

| AC | Description | Status | Evidence |
|----|-------------|--------|----------|
| AC-01 | queries raw_events, reconstructs stage durations | ✅ | `get_merged_prs()` + `get_deployments()` + `compute_pr_stages()` |
| AC-02 | Writes to vsi_stage_breakdown table | ✅ | `write_stage_breakdown()` inserts to `vsi_stage_breakdown` |
| AC-03 | Computes value-add, wait, VSM efficiency % | ✅ | `compute_vsm_metrics()` — value_add_seconds, wait_seconds, vsm_efficiency_pct |
| AC-04 | Identifies primary bottleneck | ✅ | `primary_bottleneck` field — stage with highest P50 |
| AC-05 | Grafana dashboard | ✅ | `dashboards/value-stream.json` — 11 panels, waterfall, bottleneck, trend |
| AC-06 | Unit tests with fixture sequences | ✅ | `tests/unit/test_vsi.py` — 30 tests, all passing |

## Recommendations

1. **CI event schema**: When CI pipeline events are added in v0.2, update `compute_pr_stages()` to populate the CI stage from CI completion events
2. **Rework linking**: When rework events are linked to deployments, add rework stage tracking
3. **Integration test**: Consider adding a `test_compute_integration.py` for VSM with a real TimescaleDB instance (follows pattern from `test_metrics.py`)
