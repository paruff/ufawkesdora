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

## Provisioning

### Option 1: Copy to uFawkesObs (Recommended)

The dashboard is designed to be provisioned through the uFawkesObs Grafana instance.

```bash
# Copy to uFawkesObs platform dashboards directory
cp dashboards/dora-overview.json ../uFawkesObs/dashboards/platform/dora-overview.json
```

The uFawkesObs provisioning config (`config/grafana/provisioning/dashboards/new-dashboards.yaml`) already mounts `./dashboards/platform/` to `/etc/grafana/dashboards/platform/` in the Grafana container. After copying:

```bash
docker compose restart grafana
```

The dashboard will appear in the **Platform** folder in Grafana.

### Option 2: Manual Import

1. Open Grafana UI: <http://localhost:3000>
2. Navigate to **Dashboards** → **Import**
3. Upload `dora-overview.json`
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

2. **PostgreSQL**: The `dora_snapshots` table must exist (created by `database/init/01-dora-schema.sql`) and contain data. Required columns:
   - `team_id`, `deployment_frequency`, `lead_time_hours`, `fdrt_hours`, `change_failure_rate`, `rework_rate_pct`, `dora_tier`, `proxy_metrics`

3. **Datasource UIDs**: The Grafana instance must have datasources configured with UIDs `prometheus` (Prometheus) and `PostgreSQL` (PostgreSQL). Ensure these match the uFawkesObs datasource provisioning config.
