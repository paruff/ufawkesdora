# Dashboards

This directory contains Grafana dashboards for visualizing DORA metrics computed by uFawkesDORA.

## Dashboard: DORA Overview

**File:** `dora-overview.json`
**UID:** `dora-overview`

A production-grade Grafana dashboard for tracking the five DORA metrics across teams, services, and environments.

### Panels

| Panel | Type | Datasource | Description |
|-------|------|------------|-------------|
| Header | Text | — | Dashboard title + description |
| ⚠ Proxy Metrics Active | Text | PostgreSQL | Warning banner when `proxy_metrics=true` (links to `collectors/README.md`) |
| Deployment Frequency | Stat | Prometheus | Current deployments per week |
| Lead Time for Changes | Stat | Prometheus | Current P50 lead time in hours |
| Failed Deployment Recovery Time (FDRT) | Stat | Prometheus | Current P50 FDRT in hours |
| Change Failure Rate | Stat | Prometheus | Current CFR as percentage |
| Rework Rate | Stat | Prometheus | Current rework rate as percentage |
| Deployment Frequency Trend | Timeseries | Prometheus | 30/90 day trend with DORA tier thresholds |
| Lead Time Trend | Timeseries | Prometheus | 30/90 day trend with P50 and P95 |
| FDRT Trend | Timeseries | Prometheus | 30/90 day trend |
| CFR Trend | Timeseries | Prometheus | 30/90 day trend |
| Rework Rate Trend | Timeseries | Prometheus | 30/90 day trend |
| FDRT Stage Breakdown | Table | PostgreSQL | Recent FDRT snapshots per team/service |
| Tier Legend | Row (collapsed) | — | DORA 2025 tier threshold reference |

### Datasources

| UID | Type | Purpose |
|-----|------|---------|
| `prometheus` | Prometheus | Time-series metric queries (5 stats + 5 trends) |
| `PostgreSQL` | PostgreSQL | Current snapshot data (proxy banner, FDRT breakdown, tier legend) |

### Variables

| Variable | Type | Source | Default |
|----------|------|--------|---------|
| `team` | Query (Prometheus) | `label_values(dora_deployment_frequency_per_week, team)` | `.*` |
| `service` | Query (Prometheus) | `label_values(..., service)` | `.*` |
| `environment` | Query (Prometheus) | `label_values(..., environment)` | `.*` |
| `window` | Interval | `7d,30d,90d` | `30d` |

### DORA 2025 Tier Thresholds

| Metric | Elite | High | Medium | Low |
|--------|-------|------|--------|-----|
| Deployment Frequency | ≥ 7/wk | ≥ 1/wk | < 1/wk | — |
| Lead Time for Changes | < 1h | < 24h | < 168h | ≥ 720h |
| FDRT | < 1h | < 24h | < 168h | ≥ 168h |
| Change Failure Rate | < 5% | < 10% | < 15% | ≥ 15% |
| Rework Rate | < 5% [VERIFY] | < 10% [VERIFY] | < 15% [VERIFY] | ≥ 15% [VERIFY] |

> **Note:** Rework Rate thresholds are based on CFR thresholds pending primary-source confirmation from dora.dev.

### Notes

- FDRT panels carry explicit annotations explaining the DORA 2025 reclassification from Stability to Throughput (this is **not** MTTR).
- The proxy metrics banner queries `dora_snapshots.proxy_metrics` from PostgreSQL — it appears automatically when metrics are computed from proxy data.
- Rework Rate stat panel includes tooltip: *"Only counts user-visible unplanned deployments"*.
- Two datasource approach: Prometheus for time-series, PostgreSQL for current snapshots + reference data.

## Dashboard: DORA Leading Indicators

**File:** `leading-indicators.json`
**UID:** `dora-leading-indicators`

A PostgreSQL-only Grafana dashboard for tracking leading indicators that predict DORA metric degradation before it happens. All data sourced from the `raw_events` table via SQL queries — no Prometheus pushgateway data for leading indicators.

### Panels

| Panel | Type | Datasource | Description |
|-------|------|------------|-------------|
| Header | Text | — | Dashboard title + PostgreSQL-only note |
| PR Cycle Time P90 | Stat | PostgreSQL | P90 time from PR opened to merged (predicts Lead Time) |
| PR Size (Lines Added) 14d MA | Stat | PostgreSQL | 14-day moving avg lines added per merged PR (predicts Rework Rate) |
| CI Duration 7d MA | Stat | PostgreSQL | 7-day moving avg deployment duration in minutes (predicts Deployment Frequency) |
| Rework Rate 14d MA | Stat | PostgreSQL | 14-day moving avg rework rate (predicts CFR trajectory) |
| Branch Age P90 | Stat | PostgreSQL | P90 time from first commit to PR merge (predicts Lead Time + batch size) |
| PR Cycle Time Trend | Timeseries | PostgreSQL | Daily P90 PR cycle time with threshold lines |
| PR Size Trend | Timeseries | PostgreSQL | Daily avg lines added + AI PR overlay bars (dual-axis) |
| CI Duration Trend | Timeseries | PostgreSQL | Daily avg deployment duration with threshold lines |
| Rework Rate Trend | Timeseries | PostgreSQL | Daily rework rate with threshold lines |
| Branch Age Trend | Timeseries | PostgreSQL | Daily P90 branch age with threshold lines |
| Leading → Lagging Indicator Map | Text | — | HTML table mapping each leading indicator to its predicted lagging DORA metric + capability |

### Datasources

| UID | Type | Purpose |
|-----|------|---------|
| `PostgreSQL` | PostgreSQL | All data panels — queries `raw_events` table directly |

> **Note:** Leading indicator metrics are NOT pushed to the Prometheus pushgateway. They are derived from `raw_events` via SQL. This dashboard requires the Grafana PostgreSQL datasource plugin.

### Variables

| Variable | Type | Source | Default |
|----------|------|--------|---------|
| `team` | Query (PostgreSQL) | `SELECT DISTINCT source FROM raw_events` | `All` (`%`) |
| `window` | Interval | `7d,30d,90d` | `30d` |

> **Note:** No `service` or `environment` variables — leading indicators are team-level, not service-level.

### Thresholds

| Indicator | Orange | Red |
|-----------|--------|-----|
| PR Cycle Time P90 | 12h | 24h |
| PR Size 14d MA | 200 lines | 500 lines |
| CI Duration 7d MA | 10 min | 30 min |
| Rework Rate 14d MA | 5% | 10% |
| Branch Age P90 | 24h | 72h |

### Leading → Lagging Indicator Map

| Leading Indicator | Predicts | DORA Capability |
|-------------------|----------|-----------------|
| PR Cycle Time P90 > 24hrs | Lead Time increase | Monitoring |
| PR Size 14d MA climbing | Rework Rate increase | AI Capability 5 |
| CI Duration 7d MA climbing | Deployment Frequency drop | Monitoring |
| Rework Rate 14d MA climbing | CFR trajectory | Monitoring |
| Branch Age P90 > 3 days | Lead Time increase + batch size violation | Monitoring |

### Notes

- PR Size Trend panel includes dual-axis: line for `avg_lines_added`, right-axis bars for `ai_pr_count`.
- AI-assisted PRs average 50-150% larger than baseline — monitor for Rework Rate correlation (DORA 2025).
- Rework Rate panel only counts rework events with `user_visible=true`.
- Branch Age uses `pr-event occurred_at (merged) - first_commit_at` as proxy. True branch age requires GitHub API polling.
- Grafana PostgreSQL datasource plugin availability in uFawkesObs Grafana version remains **[VERIFY]** per spec §12.

## Provisioning

### Option 1: Copy to uFawkesObs (Recommended)

The dashboard is designed to be provisioned through the uFawkesObs Grafana instance.

```bash
# Copy both dashboards to uFawkesObs platform dashboards directory
cp dashboards/dora-overview.json ../uFawkesObs/dashboards/platform/dora-overview.json
cp dashboards/leading-indicators.json ../uFawkesObs/dashboards/platform/leading-indicators.json
```

The uFawkesObs provisioning config (`config/grafana/provisioning/dashboards/new-dashboards.yaml`) already mounts `./dashboards/platform/` to `/etc/grafana/dashboards/platform/` in the Grafana container. After copying:

```bash
docker compose restart grafana
```

Both dashboards will appear in the **Platform** folder in Grafana.

### Option 2: Manual Import

1. Open Grafana UI: <http://localhost:3000>
2. Navigate to **Dashboards** → **Import**
3. Upload `dora-overview.json` or `leading-indicators.json`
4. Select **Platform** folder (or your preferred folder)

### Prerequisites

Before the dashboard displays data:

1. **Prometheus**: `compute/metrics.py` must be running and pushing metrics to the Prometheus pushgateway. Required metric names:
   - `dora_deployment_frequency_per_week`
   - `dora_lead_time_p50_hours`
   - `dora_lead_time_p95_hours`
   - `dora_fdrt_p50_hours`
   - `dora_cfr_pct`
   - `dora_rework_rate_pct`

2. **PostgreSQL**: The `raw_events` table must exist (created by `database/init/01-dora-schema.sql`) and contain data. Required for:
   - **DORA Overview**: `dora_snapshots` table with columns `team_id`, `deployment_frequency`, `lead_time_hours`, `fdrt_hours`, `change_failure_rate`, `rework_rate_pct`, `dora_tier`, `proxy_metrics`
   - **Leading Indicators**: `raw_events` table with columns `event_type`, `source`, `metadata` (JSONB), `duration_seconds`, `recorded_at`

3. **Datasource UIDs**: The Grafana instance must have datasources configured with UIDs `prometheus` (Prometheus) and `PostgreSQL` (PostgreSQL). Ensure these match the uFawkesObs datasource provisioning config.

4. **PostgreSQL Plugin**: The Leading Indicators dashboard requires the [Grafana PostgreSQL datasource plugin](https://grafana.com/grafana/plugins/grafana-postgresql-datasource/). Availability in the uFawkesObs Grafana image remains **[VERIFY]** per spec §12.
