# Test Report — Issue 15: Value Stream Indicators

## Test Results

**Overall: PASS** ✅ — 30/30 tests passing, 0 failures, 0 errors

| Test Suite | Tests | Passed | Failed |
|-----------|-------|--------|--------|
| `test_vsi.py` | 30 | 30 | 0 |
| Existing tests (no regression) | — | All pre-passing tests still pass | — |

## Acceptance Criteria Verification

| AC | Description | Test Coverage | Result |
|----|-------------|--------------|--------|
| AC-01 | `compute/vsi.py` queries raw_events, reconstructs stage durations | `test_coding_stage_correct`, `test_review_stage_correct`, `test_deploy_stage_links_nearest_deployment`, `test_ci_stage_skipped`, `test_skip_pr_without_opened_at`, `test_multiple_deployments_same_repo` | ✅ PASS |
| AC-02 | Writes to vsi_stage_breakdown table | `test_write_stage_breakdown`, `test_write_stage_breakdown_empty` | ✅ PASS |
| AC-03 | Computes value-add time, wait time, VSM efficiency % | `test_vsm_efficiency_calculation`, `test_value_add_wait_breakdown` | ✅ PASS |
| AC-04 | Identifies primary bottleneck (highest wait time stage) | `test_bottleneck_identification`, `test_bottleneck_prefers_nonzero_stages`, `test_aggregate_stage_stats` | ✅ PASS |
| AC-05 | `dashboards/value-stream.json` Grafana dashboard | Valid Grafana provisioning JSON with 11 panels including waterfall, bottleneck highlight, efficiency trend | ✅ PASS |
| AC-06 | `tests/unit/test_vsi.py` with representative event fixture sequences | 30 tests covering stage computation, VSM metrics, bottleneck, edge cases, DB mocking, CLI, formatting | ✅ PASS |

## Detailed Test Breakdown

### TestComputeDeploymentId (1 test)
- `test_generates_correct_id` ✅

### TestComputePRStages (7 tests)
- `test_coding_stage_correct` ✅ — Coding time = opened_at - first_commit_at
- `test_review_stage_correct` ✅ — Review time = merged_at - opened_at
- `test_deploy_stage_links_nearest_deployment` ✅ — Deploy time matches closest deployment after merge
- `test_deploy_pending_when_no_deployment` ✅ — Deploy is "pending" when no deployment found
- `test_ci_stage_skipped` ✅ — CI stage is skipped for v0.1
- `test_skip_pr_without_opened_at` ✅ — PRs with missing timestamps are skipped
- `test_multiple_deployments_same_repo` ✅ — Correct deployment matching with multiple deployments

### TestComputeVSMMetrics (5 tests)
- `test_vsm_efficiency_calculation` ✅ — 71.4% efficiency with 9k value-add / 12.6k total
- `test_bottleneck_identification` ✅ — Review identified as bottleneck (highest median)
- `test_value_add_wait_breakdown` ✅ — Value-add = coding+deploy, Wait = review
- `test_bottleneck_prefers_nonzero_stages` ✅ — CI (0) excluded from bottleneck calc
- `test_aggregate_stage_stats` ✅ — avg, p50, p95, sample_count per stage

### TestFormatDuration (4 tests)
- Seconds, minutes, hours, days formatting ✅

### TestParseArgs (7 tests)
- Defaults, custom window, team filter, pushgateway, verbose, JSON, short flags ✅

### TestVSIDB (4 tests)
- `test_init_requires_dsn` ✅
- `test_init_uses_env_var` ✅
- `test_write_stage_breakdown` ✅
- `test_write_stage_breakdown_empty` ✅

### TestPrintVSMTable (2 tests)
- `test_prints_with_data` ✅
- `test_prints_empty` ✅

## Lint Results

| File | Status |
|------|--------|
| `compute/vsi.py` | ✅ Clean |
| `tests/unit/test_vsi.py` | ✅ Clean |

## Risks

- **No regression risk**: All new tests pass, existing passing tests unaffected
- **CI events not defined**: CI stage is skipped for v0.1 (documented in spec §7)
- **JSON dashboard**: The `dashboards/value-stream.json` is a Grafana provisioning file; it's not validated by Python tools. It follows the same format as existing dashboards (`dora-overview.json`, `leading-indicators.json`, etc.)
