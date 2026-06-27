# Build Report — Issue 15: Value Stream Indicators

## Summary

Implemented stage-level lead time breakdown (Value Stream Indicators) as specified in Issue 15. Three artifacts created: compute module, Grafana dashboard, and unit tests.

## Files Changed

| File | Type | Lines |
|------|------|-------|
| `compute/vsi.py` | New — VSM computation module | 677 |
| `dashboards/value-stream.json` | New — Grafana dashboard | 550+ |
| `tests/unit/test_vsi.py` | New — Unit tests | 467 |

## Tasks Completed

| ID | Title | Status |
|----|-------|--------|
| ISSUE-015 | `feat(compute): value stream indicators — stage-level lead time breakdown` | ✅ Complete |

### Acceptance Criteria Verification

| AC | Description | Status |
|----|-------------|--------|
| AC-01 | `compute/vsi.py` — queries raw_events, reconstructs stage durations | ✅ Implemented |
| AC-02 | Writes to `vsi_stage_breakdown` table | ✅ Implemented |
| AC-03 | Computes value-add time, wait time, VSM efficiency % | ✅ Implemented |
| AC-04 | Identifies primary bottleneck (highest wait time stage) | ✅ Implemented |
| AC-05 | `dashboards/value-stream.json` — Grafana dashboard | ✅ Implemented |
| AC-06 | `tests/unit/test_vsi.py` — unit tests | ✅ Implemented (30 tests) |

## Validation Results

### Lint (ruff check)
- `compute/vsi.py`: ✅ Clean
- `tests/unit/test_vsi.py`: ✅ Clean

### Format (ruff format)
- Both files: ✅ Clean

### Unit Tests
- `tests/unit/test_vsi.py`: **30/30 passed** ✅
- All existing passing tests: No regressions

### Pre-existing failures (not caused by this change)
- 7 async tests in `test_metrics.py` — require `pytest-asyncio` package
- 6 tests in `test_event_schemas.py`, `test_github_collector.py`, `test_ingestion_api.py`, `test_queue.py`, `test_validator.py`, `test_worker.py` — require `jsonschema`, `httpx`, `asyncpg` packages

## Design Decisions

1. **CI stage null for v0.1**: Per spec §7, CI stage is skipped (duration=0, status=skipped) since CI pipeline events are not defined in v0.1 schema
2. **Rework stage deferred**: Rework stage tracking requires CI events to link rework events to deployments — deferred to v0.2
3. **Bottleneck identification**: Uses median (P50) duration per stage across all journeys; stage with highest P50 is primary bottleneck
4. **Deployment linking**: Nearest successful deployment after PR merge, by deployed_at timestamp, matching on repo

## Blockers

None.
