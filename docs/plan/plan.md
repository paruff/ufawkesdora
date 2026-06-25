# uFawkesDORA: Revised Strategic Plan & GitHub Issues

_Revision 2 — incorporates Resource Plane architecture with PostgreSQL event store,
TimescaleDB extension, corrected Alertmanager data flow, message queue pattern,
and proper multi-database init. Based on DORA 2025/2026 research._
_Last updated: 2026-06-22_

---

## Part 1: Architecture Decision Record

### The definitive plane model

uFawkesDORA is a **stateless compute plane** that reads from and writes to a
**stateful resource plane**. These two planes have completely independent lifecycles.
You can tear down, rebuild, or rewrite the entire uFawkesDORA compute layer tomorrow
and your historical DORA event data survives untouched in the resource plane.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  EVENT SOURCES                                                              │
│                                                                             │
│  Woodpecker CI ──────(HTTP POST, canonical schema)──────────────────────┐  │
│  Portainer webhooks ─(HTTP POST, canonical schema)──────────────────────┤  │
│  GitHub Actions ─────(HTTP POST, canonical schema)──────────────────────┤  │
│  Incident webhook ───(HTTP POST, canonical schema)──────────────────────┘  │
│  (Grafana OnCall / PagerDuty / manual curl)         │                      │
└─────────────────────────────────────────────────────┼──────────────────────┘
                                                      │
                                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  uFawkesDORA COMPUTE PLANE  (stateless — freely redeployable)              │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Event Queue  (Postgres table, SKIP LOCKED pattern)                  │  │
│  │  Absorbs events during ingestion engine restarts. No event loss.     │  │
│  └────────────────────────────┬─────────────────────────────────────────┘  │
│                               │                                             │
│  ┌────────────────────────────▼─────────────────────────────────────────┐  │
│  │  Ingestion API  (FastAPI, stateless)                                 │  │
│  │  - Validates canonical event schema                                  │  │
│  │  - Enqueues to Event Queue                                           │  │
│  │  - Returns 422 with detail on schema violation                       │  │
│  └────────────────────────────┬─────────────────────────────────────────┘  │
│                               │                                             │
│  ┌────────────────────────────▼─────────────────────────────────────────┐  │
│  │  Event Processor  (background worker, stateless)                     │  │
│  │  - Dequeues from Event Queue                                         │  │
│  │  - Writes raw events → Resource Plane PostgreSQL (raw_events table)  │  │
│  │  - Pushes OTel counters → uFawkesObs OTel Collector                 │  │
│  │  - Writes structured logs → uFawkesObs Loki                         │  │
│  └────────────────────────────┬─────────────────────────────────────────┘  │
│                               │                                             │
│  ┌────────────────────────────▼─────────────────────────────────────────┐  │
│  │  Metric Compute Job  (cron, stateless)                               │  │
│  │  - Reads raw events from PostgreSQL                                  │  │
│  │  - Computes all 5 DORA metrics + Rework Rate + VSM indicators        │  │
│  │  - Writes derived metrics → PostgreSQL (dora_snapshots table)        │  │
│  │  - Pushes metrics → uFawkesObs Prometheus via pushgateway            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                 │                              │
                 │ (SQL queries,               │ (PromQL, Loki queries)
                 │  long-retention data)        │
                 ▼                              ▼
┌────────────────────────────┐    ┌─────────────────────────────────────────┐
│  RESOURCE PLANE            │    │  uFawkesObs                             │
│                            │    │                                         │
│  PostgreSQL 16 +           │    │  Prometheus ← OTel Collector            │
│  TimescaleDB extension     │    │  (derived metrics, time-series,         │
│                            │    │   alerting rules, Grafana source)       │
│  Schemas:                  │    │                                         │
│  - dora_metrics (events,   │    │  Loki                                   │
│    snapshots, archetypes,  │    │  (raw event logs, debug, audit trail)   │
│    wellbeing surveys)      │    │                                         │
│  - infisical                │    │  Grafana                                │
│  - defectdojo               │    │  (reads BOTH Prometheus AND Postgres    │
│                            │    │   via Postgres datasource plugin)       │
│  Network: fawkes-resource- │    │                                         │
│  net (isolated)            │    │  Alertmanager                           │
│                            │    │  (routes notifications OUT — Slack,     │
│                            │    │   email, PagerDuty — never feeds IN)    │
└────────────────────────────┘    └─────────────────────────────────────────┘
                 ▲                              ▲
                 └──────────────┬───────────────┘
                                │
                    ┌───────────▼──────────────┐
                    │  uFawkesObs Grafana       │
                    │  (single rendering point  │
                    │  for all DORA dashboards) │
                    │                           │
                    │  DORA Overview            │
                    │  Leading Indicators       │
                    │  AI Impact                │
                    │  Archetype Profile        │
                    │  Value Stream             │
                    └───────────────────────────┘
                                │
                    ┌───────────▼──────────────┐
                    │  DELIVERY BEYOND          │
                    │  DASHBOARDS               │
                    │                           │
                    │  Alertmanager → Slack     │
                    │  Weekly digest → Markdown │
                    │  PR annotations           │
                    └───────────────────────────┘
```

### Four architectural decisions and their rationale

**Decision 1: PostgreSQL with TimescaleDB as the raw event store**

Raw DORA events are not pure time-series data — they have relational structure
(a `rework-event` links to a `deployment-event` via `deployment_sha`; a
`pr-event` links to a `deployment-event` via `commit_sha`; `archetype_history`
links to `wellbeing_surveys`). These joins are SQL, not PromQL. Prometheus cannot
express them.

At the same time, DORA metric queries are time-range aggregations with percentiles
(lead time P50, FDRT P90). TimescaleDB's `time_bucket()` and `percentile_agg()`
functions make these natural SQL without the index-tuning overhead of vanilla Postgres.

**The role split is therefore:**

- PostgreSQL + TimescaleDB: raw events (long retention, complex joins, archetype
  history, wellbeing survey responses, VSM stage breakdown)
- Prometheus: derived metrics (computed from events by the cron job, pushed via
  pushgateway; powers alerting rules and Grafana time-series panels)
- Loki: raw event logs (debug trail, structured JSON, useful for leading indicator
  queries at log granularity)

This avoids both the dual-ingestion problem (one write path produces all three outputs)
and the "wrong tool for the job" problem (Prometheus for joins, SQL for time-series).

**Decision 2: PostgreSQL event queue (SKIP LOCKED) for zero event loss**

The ingestion API is stateless and freely redeployable. But "freely redeployable"
without a queue means events arriving during a restart are lost. At low deployment
frequency (<10/day) this is an acceptable risk, but it should be a documented
decision, not a silent gap.

The queue uses a `event_queue` table in Postgres with a `status` column
(`pending` / `processing` / `done`). Workers claim rows with
`SELECT FOR UPDATE SKIP LOCKED LIMIT 1`. This pattern requires no additional
infrastructure (no Redis, no RabbitMQ, no NATS) — it runs on the same Postgres
instance already in the resource plane. It is simple, inspectable, and sufficient
for this scale. The acknowledged ceiling: throughput degrades above ~500 events/second,
which this platform will not approach.

**Decision 3: Alertmanager routes OUT, never feeds IN**

Alertmanager is a notification router. It fires when Prometheus alerting rules trip.
It must not appear in the event ingestion data flow.

Incident events (the data that drives FDRT and contributes to CFR) come from an
incident management source: Grafana OnCall webhook, PagerDuty webhook, or a manual
`curl` to the ingestion API's `/event` endpoint. This is a CI/CD-level concern
(the same teams triggering deployments can trigger incident events) — not an
observability-layer concern.

**Decision 4: Multi-database PostgreSQL via init scripts, not env vars**

`POSTGRES_MULTIPLE_DATABASES` is not a standard Postgres environment variable. It
silently does nothing in the official `postgres:16-alpine` image. The correct pattern
is an init script in `/docker-entrypoint-initdb.d/` that creates additional databases
and grants per-database roles with minimum necessary privileges.

---

## Part 2: DORA 2025/2026 Metric Model (unchanged from previous revision)

### The five metrics

| Metric                              | Category   | Notes                                                                                  |
| ----------------------------------- | ---------- | -------------------------------------------------------------------------------------- |
| **Deployment Frequency**            | Throughput | Rate of successful deployments to production                                           |
| **Lead Time for Changes**           | Throughput | First commit → deployed; P50 and P95                                                   |
| **Failed Deployment Recovery Time** | Throughput | Renamed MTTR; time between failed deploy and next successful deploy of same service    |
| **Change Failure Rate**             | Stability  | Failed or rolled-back deployments / total deployments                                  |
| **Rework Rate**                     | Stability  | NEW in 2024/2025; unplanned deployments fixing user-visible issues / total deployments |

FDRT moved to Throughput because fast recovery enables faster re-deployment. This
changes the alerting model: an FDRT spike is a throughput alarm, not just a stability
alarm.

### The seven archetypes (replaces Elite/High/Medium/Low)

| Archetype                                           | ~Share | Signature                                           |
| --------------------------------------------------- | ------ | --------------------------------------------------- |
| Harmonious high-achievers                           | 20%    | High throughput, low instability, high wellbeing    |
| Pragmatic performers                                | 20%    | High speed/stability, lower engagement              |
| Stable and methodical                               | 15%    | High quality, sustainable pace, lower throughput    |
| Constrained by process                              | 17%    | Stable systems, process overhead consuming capacity |
| Legacy bottleneck                                   | 11%    | Reactive, unstable systems, low morale              |
| High impact, low cadence                            | 7%     | High-value output, low throughput, high instability |
| _(seventh per primary source — verify at dora.dev)_ | ~10%   | —                                                   |

Archetype classification requires delivery metrics AND wellbeing signals. An
uFawkesDORA that only uses telemetry will misclassify teams — this is documented
and the classifier expresses a confidence score.

### Beyond the five: what elite teams also track

- **Reliability** — SLO adherence, uptime; quasi-metric, strong outcome correlation
- **Wellbeing signals** — burnout, friction, valuable work %; survey-based (SPACE framework)
- **AI impact signals** — PR size trend (AI inflates ~50-150%), code churn rate, Rework Rate trend
- **Value stream efficiency** — where lead time is spent stage-by-stage; VSM layer above DORA

---

## Part 3: Repository Structure

```
uFawkesDORA/
├── events/                          # Canonical event schemas (the API contract)
│   ├── deployment-event.schema.json
│   ├── incident-event.schema.json
│   ├── pr-event.schema.json
│   ├── rework-event.schema.json
│   └── README.md                    # Schema field reference + versioning policy
│
├── ingestion/                       # Stateless compute plane
│   ├── api/
│   │   ├── main.py                  # FastAPI app: POST /event, POST /health
│   │   ├── validator.py             # JSON schema validation
│   │   └── queue.py                 # Postgres SKIP LOCKED enqueue
│   ├── processor/
│   │   ├── worker.py                # Dequeue → write Postgres + OTel + Loki
│   │   ├── otel_exporter.py         # Push OTel counters to uFawkesObs collector
│   │   └── loki_exporter.py         # Structured log push to Loki
│   └── Dockerfile
│
├── compute/                         # Metric computation (cron, stateless)
│   ├── metrics.py                   # Five DORA metrics from Postgres raw events
│   ├── archetype.py                 # Seven archetype classifier
│   ├── vsi.py                       # Value stream indicators (stage breakdown)
│   ├── pushgateway.py               # Push derived metrics to Prometheus pushgateway
│   ├── archetype_survey.md          # Minimal wellbeing survey (3-5 questions)
│   └── Dockerfile
│
├── database/                        # Resource plane database definitions
│   ├── init/
│   │   ├── 00-create-databases.sh   # Creates dora_metrics, infisical, defectdojo DBs
│   │   ├── 01-dora-schema.sql       # dora_metrics schema (raw_events, event_queue,
│   │   │                            #   dora_snapshots, archetype_history,
│   │   │                            #   wellbeing_surveys, vsi_stage_breakdown)
│   │   └── 02-dora-roles.sql        # Least-privilege roles per service
│   ├── migrations/                  # Forward-only SQL migrations (numbered)
│   │   └── 001-initial-schema.sql
│   └── timescaledb/
│       └── hypertables.sql          # Convert time-series tables to hypertables
│
├── dashboards/                      # Grafana dashboard JSON (provisioned to uFawkesObs)
│   ├── dora-overview.json
│   ├── leading-indicators.json
│   ├── ai-impact.json
│   ├── archetype-profile.json
│   └── value-stream.json
│
├── alerts/                          # Prometheus alerting rules
│   ├── dora-regression.yaml         # Regression-based (vs baseline), not threshold-based
│   └── leading-indicator.yaml       # Early warning signals
│
├── notifications/                   # Delivery beyond dashboards
│   ├── digest/
│   │   └── generate_digest.py       # Weekly Markdown digest
│   ├── slack/
│   │   └── slack_webhook.py         # Slack delivery
│   └── pr_annotation/
│       └── annotate.py              # PR lead time comment
│
├── collectors/                      # How to wire event sources
│   ├── github/                      # Reusable GitHub Actions workflows
│   ├── woodpecker/                  # Woodpecker pipeline snippet
│   └── generic/                     # curl examples for any source
│
├── tests/
│   ├── unit/                        # Already exists (9 commits)
│   └── acceptance/
│       ├── test_event_pipeline.sh   # Event in → metric queryable end-to-end
│       └── fixtures/                # Sample event JSON for each schema
│
├── docker-compose.yml               # uFawkesDORA compute plane only
│                                    # (does NOT contain Postgres — that's resource plane)
├── docker-compose.dev.yml           # Dev override: includes local Postgres for solo dev
└── .env.example                     # POSTGRES_URL, OTEL_ENDPOINT, LOKI_URL, etc.
```

### How uFawkesDORA attaches to the resource plane

```yaml
# docker-compose.yml (uFawkesDORA — compute plane only)
services:
  ingestion-api:
    build: ./ingestion
    environment:
      - POSTGRES_URL=${POSTGRES_URL} # Points to resource plane Postgres
      - OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT}
      - LOKI_URL=${LOKI_URL}
    networks:
      - fawkes-resource-net # External — defined in resource plane compose
      - dora-internal # Internal — ingestion API ↔ processor only

  event-processor:
    build: ./ingestion
    command: python processor/worker.py
    environment:
      - POSTGRES_URL=${POSTGRES_URL}
      - OTEL_EXPORTER_OTLP_ENDPOINT=${OTEL_EXPORTER_OTLP_ENDPOINT}
      - LOKI_URL=${LOKI_URL}
    networks:
      - fawkes-resource-net
      - dora-internal
    depends_on:
      - ingestion-api

  metric-compute:
    build: ./compute
    environment:
      - POSTGRES_URL=${POSTGRES_URL}
      - PUSHGATEWAY_URL=${PUSHGATEWAY_URL} # uFawkesObs Prometheus pushgateway
    networks:
      - fawkes-resource-net

networks:
  fawkes-resource-net:
    external: true # Defined in resource plane — not owned by this compose
    name: fawkes-resource-net
  dora-internal:
    driver: bridge
    internal: true # No external routing — ingestion API ↔ processor only
```

### Resource plane Postgres definition (in fawkes resource plane compose)

```yaml
# In fawkes/infra/resource-plane/docker-compose.yml (NOT in uFawkesDORA repo)
services:
  shared-postgres:
    image: timescale/timescaledb:latest-pg16
    container_name: fawkes-resource-postgres
    restart: unless-stopped
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_ADMIN_PASSWORD} # From Infisical
      POSTGRES_USER: postgres
      POSTGRES_DB: postgres # Admin DB only — app DBs created by init scripts
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./database/init:/docker-entrypoint-initdb.d:ro # Init scripts from uFawkesDORA
    networks:
      - fawkes-resource-net
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 1G

volumes:
  postgres-data:

networks:
  fawkes-resource-net:
    name: fawkes-resource-net
    driver: bridge
```

Note: `timescale/timescaledb:latest-pg16` replaces `postgres:16-alpine` to include
the TimescaleDB extension. The init scripts in `database/init/` live in the
uFawkesDORA repo and are bind-mounted into the resource plane container — this keeps
the schema definition co-located with the code that uses it.

### Database init script (the correct multi-database pattern)

```bash
# database/init/00-create-databases.sh
#!/bin/bash
# Creates application databases with least-privilege roles.
# Runs once on first container start. Safe to re-run (idempotent via IF NOT EXISTS).

set -e

create_database() {
  local DB=$1
  local ROLE=$2
  local PASSWORD=$3

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" << EOSQL
    SELECT 'CREATE DATABASE ${DB}' WHERE NOT EXISTS
      (SELECT FROM pg_database WHERE datname = '${DB}')\gexec
    SELECT 'CREATE ROLE ${ROLE} WITH LOGIN PASSWORD ''${PASSWORD}''' WHERE NOT EXISTS
      (SELECT FROM pg_roles WHERE rolname = '${ROLE}')\gexec
    GRANT CONNECT ON DATABASE ${DB} TO ${ROLE};
    \c ${DB}
    GRANT USAGE ON SCHEMA public TO ${ROLE};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO ${ROLE};
EOSQL
}

create_database "dora_metrics"  "dora_app"      "${DORA_DB_PASSWORD}"
create_database "infisical"     "infisical_app" "${INFISICAL_DB_PASSWORD}"
create_database "defectdojo"    "dojo_app"      "${DEFECTDOJO_DB_PASSWORD}"

echo "Databases initialized."
```

### Database schema (TimescaleDB)

```sql
-- database/init/01-dora-schema.sql
\c dora_metrics

-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Raw event queue (SKIP LOCKED pattern for zero event loss)
CREATE TABLE IF NOT EXISTS event_queue (
  id          BIGSERIAL PRIMARY KEY,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  event_type  TEXT NOT NULL,
  payload     JSONB NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending'  -- pending | processing | done | failed
                CHECK (status IN ('pending','processing','done','failed')),
  attempts    INT NOT NULL DEFAULT 0,
  error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_queue_status ON event_queue (status) WHERE status = 'pending';

-- Raw events (long-retention store, relational joins, archetype history)
CREATE TABLE IF NOT EXISTS raw_events (
  id              BIGSERIAL,
  event_type      TEXT NOT NULL,
  occurred_at     TIMESTAMPTZ NOT NULL,
  repo            TEXT NOT NULL,
  service         TEXT,
  environment     TEXT,
  payload         JSONB NOT NULL,
  schema_version  TEXT NOT NULL DEFAULT '1.0'
);
SELECT create_hypertable('raw_events', 'occurred_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_raw_events_repo ON raw_events (repo, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_events_type ON raw_events (event_type, occurred_at DESC);

-- Computed DORA snapshots (written by metric compute job)
CREATE TABLE IF NOT EXISTS dora_snapshots (
  id                              BIGSERIAL,
  computed_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  period_start                    TIMESTAMPTZ NOT NULL,
  period_end                      TIMESTAMPTZ NOT NULL,
  repo                            TEXT NOT NULL,
  service                         TEXT,
  deployment_frequency_per_week   NUMERIC,
  lead_time_p50_hours             NUMERIC,
  lead_time_p95_hours             NUMERIC,
  fdrt_p50_hours                  NUMERIC,
  change_failure_rate_pct         NUMERIC,
  rework_rate_pct                 NUMERIC,
  proxy_metrics                   BOOLEAN NOT NULL DEFAULT FALSE,
  window_days                     INT NOT NULL DEFAULT 30
);
SELECT create_hypertable('dora_snapshots', 'computed_at', if_not_exists => TRUE);

-- Archetype classification history
CREATE TABLE IF NOT EXISTS archetype_history (
  id              BIGSERIAL PRIMARY KEY,
  classified_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  repo            TEXT NOT NULL,
  archetype       TEXT NOT NULL,
  confidence      NUMERIC NOT NULL,
  wellbeing_data  BOOLEAN NOT NULL DEFAULT FALSE,
  metrics_input   JSONB NOT NULL,
  wellbeing_input JSONB
);

-- Wellbeing survey responses (quarterly)
CREATE TABLE IF NOT EXISTS wellbeing_surveys (
  id              BIGSERIAL PRIMARY KEY,
  submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  repo            TEXT NOT NULL,
  quarter         TEXT NOT NULL,  -- YYYY-QN
  burnout_score   INT CHECK (burnout_score BETWEEN 1 AND 5),
  friction_score  INT CHECK (friction_score BETWEEN 1 AND 5),
  valuable_work_pct INT CHECK (valuable_work_pct BETWEEN 0 AND 100),
  recommend_score INT CHECK (recommend_score BETWEEN 1 AND 5)
);

-- Value stream stage breakdown (VSM layer)
CREATE TABLE IF NOT EXISTS vsi_stage_breakdown (
  id                    BIGSERIAL,
  measured_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  repo                  TEXT NOT NULL,
  commit_sha            TEXT NOT NULL,
  coding_hours          NUMERIC,  -- first_commit → PR open
  review_hours          NUMERIC,  -- PR open → approval
  ci_hours              NUMERIC,  -- PR merge → CI green
  deploy_hours          NUMERIC,  -- CI green → deployed
  rework_hours          NUMERIC,  -- deployed → rework event (if any)
  total_lead_time_hours NUMERIC,
  value_add_pct         NUMERIC   -- (coding + ci + deploy) / total * 100
);
SELECT create_hypertable('vsi_stage_breakdown', 'measured_at', if_not_exists => TRUE);
```

---

## Part 4: Incident Event Clarification

Incident events enter uFawkesDORA via the same `/event` endpoint as deployment events.
They are emitted by the incident management tool, not by Alertmanager.

```
CORRECT data flow for FDRT calculation:
  1. Woodpecker/GitHub → POST /event  { event_type: "deployment", status: "failed" }
  2. PagerDuty/Grafana OnCall → POST /event  { event_type: "incident", started_at: T1 }
  3. PagerDuty/Grafana OnCall → POST /event  { event_type: "incident", resolved_at: T2 }
  4. Woodpecker/GitHub → POST /event  { event_type: "deployment", status: "success" }
  5. compute/metrics.py: FDRT = T4 (next successful deploy) - T1 (failed deploy)

CORRECT data flow for Alertmanager:
  Prometheus alerting rule fires (CFR > baseline) →
  Alertmanager → routes notification → Slack/email/PagerDuty

Alertmanager NEVER appears as an input to POST /event. It is always downstream.
```

For teams without a PagerDuty integration, a `collectors/manual-incident/` template
provides a curl command that engineers run when an incident is declared and when it's
resolved. This keeps FDRT measurement accessible without requiring an incident
management SaaS subscription.

---

## Part 5: GitHub Issues

### Phase 0 — Foundation

---

**Issue 1**
`feat(database): implement resource plane Postgres schema with TimescaleDB`
**Labels:** `feat`, `tier-1`, `phase-0`, `infra`
**Estimate:** 1 session (2hrs)
**No dependencies**

**Summary**
Define the PostgreSQL + TimescaleDB schema for all uFawkesDORA data: event queue,
raw events, DORA snapshots, archetype history, wellbeing surveys, and VSM stage
breakdown. This is the foundational data model — everything else reads from or
writes to these tables.

**Context**
The resource plane Postgres instance (defined in fawkes resource plane, not in
uFawkesDORA) will host a `dora_metrics` database. The schema definition and init
scripts live in uFawkesDORA and are bind-mounted into the resource plane container.
Using `timescale/timescaledb:latest-pg16` instead of `postgres:16-alpine` enables
`time_bucket()` and `percentile_agg()` for time-series metric queries without the
index overhead of vanilla Postgres.

**Acceptance Criteria**

- [ ] `database/init/00-create-databases.sh` — creates `dora_metrics`, `infisical`,
      `defectdojo` databases with least-privilege roles via psql, not env vars.
      Script is idempotent (safe to re-run).
- [ ] `database/init/01-dora-schema.sql` — creates all tables per schema above:
      `event_queue`, `raw_events`, `dora_snapshots`, `archetype_history`,
      `wellbeing_surveys`, `vsi_stage_breakdown`
- [ ] `database/init/02-dora-roles.sql` — creates `dora_app` role with
      least-privilege grants: INSERT on `event_queue`, SELECT/INSERT on `raw_events`,
      INSERT on `dora_snapshots` etc. NO superuser, NO schema ownership.
- [ ] `database/timescaledb/hypertables.sql` — converts `raw_events`,
      `dora_snapshots`, `vsi_stage_breakdown` to TimescaleDB hypertables
- [ ] `database/migrations/001-initial-schema.sql` — forward-only migration
      matching the init scripts (first run = migration 001)
- [ ] `tests/unit/test_schema.py` — spins up a test Postgres container via
      `testcontainers`, applies all init scripts, verifies all tables exist, verifies
      hypertable creation, verifies role permissions are correct (not superuser)
- [ ] `docker-compose.dev.yml` includes a local TimescaleDB container for solo
      development without the full resource plane
- [ ] All tests pass in CI

**DORA capability:** AI Capability 2 (Healthy data ecosystems)
**Blocks:** Issues 2, 3, 4, 5, 6

---

**Issue 2**
`feat(events): define canonical event schemas for all five DORA metrics`
**Labels:** `feat`, `tier-1`, `phase-0`
**Estimate:** 1 session
**No dependencies** (can run in parallel with Issue 1)

**Summary**
Define the JSON schemas that all event sources must conform to. These schemas are
the API contract between any CI/CD system and uFawkesDORA. Stability of these schemas
is critical — a schema change breaks all connected collectors.

**Acceptance Criteria**

- [ ] `events/deployment-event.schema.json` — required fields: `schema_version`,
      `event_type` ("deployment"), `repo`, `service`, `environment`, `commit_sha`,
      `deployed_at` (ISO8601), `status` ("success" | "failed" | "rollback"),
      `pipeline_url`; optional: `deploy_duration_seconds`, `ai_assisted` (bool)
- [ ] `events/incident-event.schema.json` — required: `schema_version`, `event_type`
      ("incident"), `incident_id`, `repo`, `service`, `status` ("opened" | "resolved"),
      `occurred_at`; optional: `linked_deployment_sha`, `severity`
- [ ] `events/pr-event.schema.json` — required: `schema_version`, `event_type` ("pr"),
      `repo`, `pr_number`, `commit_sha`, `status` ("opened" | "merged" | "closed"),
      `occurred_at`, `first_commit_at`; optional: `lines_added`, `lines_deleted`,
      `ai_assisted` (bool)
- [ ] `events/rework-event.schema.json` — required: `schema_version`, `event_type`
      ("rework"), `repo`, `deployment_sha`, `rework_type` ("hotfix" | "rollback" | "patch"),
      `triggered_at`, `user_visible` (bool)
- [ ] All schemas include a `version` field starting at `"1.0"` with a documented
      versioning policy in `events/README.md`: minor = backward-compatible field additions,
      major = field removals or type changes (require collector updates)
- [ ] `tests/unit/test_event_schemas.py` — validates each schema using `jsonschema`;
      tests both valid and invalid payloads; all pass in CI
- [ ] `events/README.md` — field reference, versioning policy, and how to determine
      `rework` vs normal deployment

**DORA capability:** AI Capability 2 (Healthy data ecosystems)
**Blocks:** Issues 3, 4, 5, 6

---

**Issue 3**
`feat(ingestion): stateless ingestion API with Postgres event queue`
**Labels:** `feat`, `tier-1`, `phase-0`
**Estimate:** 1-2 sessions
**Depends on:** Issues 1, 2

**Summary**
Implement the stateless FastAPI ingestion API that accepts events on `POST /event`,
validates the canonical schema, and enqueues to the Postgres `event_queue` table
using the SKIP LOCKED pattern. This is the only component that needs to be reachable
from external event sources.

**Context**
The queue absorbs events during ingestion engine restarts so no event is lost during
redeployment. The SKIP LOCKED approach uses the resource plane Postgres instance —
no additional infrastructure (Redis, RabbitMQ, NATS) required. Known ceiling:
~500 events/second throughput; documented and sufficient for this scale.

**Acceptance Criteria**

- [ ] `ingestion/api/main.py` — FastAPI app exposing:
  - `POST /event` — accepts JSON, validates schema, enqueues, returns `{"queued": true, "id": N}`
  - `GET /health` — returns `{"status": "ok", "queue_depth": N}`
  - `POST /event/batch` — accepts array of events, validates all, enqueues in one transaction
- [ ] `ingestion/api/validator.py` — validates `event_type` field first, then routes
      to the correct schema; returns structured 422 with field-level errors (not just "invalid")
- [ ] `ingestion/api/queue.py` — enqueue with `INSERT INTO event_queue (event_type, payload)
VALUES ($1, $2) RETURNING id`; connection pool via `asyncpg`
- [ ] `ingestion/processor/worker.py` — dequeue loop: `SELECT id, payload FROM event_queue
WHERE status='pending' ORDER BY received_at LIMIT 1 FOR UPDATE SKIP LOCKED`;
      on success: write to `raw_events`, push OTel counter, push Loki log, update status='done';
      on failure: increment attempts, update status='failed' if attempts >= 3
- [ ] `ingestion/Dockerfile` — multi-stage build, non-root user, health check
- [ ] `tests/unit/test_ingestion_api.py` — covers: valid event accepted (201),
      invalid schema rejected (422 with field errors), queue depth in health check,
      duplicate events handled
- [ ] `tests/unit/test_worker.py` — covers: dequeue success path, dequeue failure
      path (attempts increment), SKIP LOCKED (two workers don't claim same row)
- [ ] Evidence: `curl -X POST http://localhost:8088/event -d @fixtures/deployment-success.json`
      → `{"queued": true, "id": 1}` → row appears in `event_queue` with status 'done'
      → row appears in `raw_events` → OTel span visible in uFawkesObs Tempo

**DORA capability:** AI Capability 2 (Healthy data ecosystems)
**Blocks:** Issues 7, 8

---

**Issue 4**
`feat(compute): five DORA metrics + Rework Rate from PostgreSQL`
**Labels:** `feat`, `tier-1`, `phase-0`
**Estimate:** 2 sessions
**Depends on:** Issues 1, 2

**Summary**
Implement `compute/metrics.py` — the reference computation of all five DORA delivery
metrics from the Postgres `raw_events` table, using TimescaleDB functions for
time-series aggregation. Output to `dora_snapshots` table AND pushgateway (for
Grafana time-series panels and alerting).

**Context**
The 2025 metric changes that must be implemented correctly:

- FDRT is time between a failed deployment and the _next successful deployment of
  the same service_ — not time to resolve an incident. This is the 2025
  reclassification from Stability to Throughput.
- Rework Rate uses `user_visible=true` rework events only, divided by total
  deployments. Hotfixes for internal issues do not count.

**TimescaleDB queries for each metric:**

```sql
-- Deployment Frequency (deploys/week over window)
SELECT time_bucket('1 week', occurred_at) AS week,
       repo,
       COUNT(*) AS deployments
FROM raw_events
WHERE event_type = 'deployment'
  AND payload->>'status' = 'success'
  AND occurred_at >= NOW() - INTERVAL '%s days'
GROUP BY 1, 2 ORDER BY 1;

-- Lead Time P50 (hours from first_commit to deployed_at)
SELECT percentile_agg(
  EXTRACT(EPOCH FROM (
    (payload->>'deployed_at')::timestamptz -
    (payload->>'first_commit_at')::timestamptz
  )) / 3600
) AS lead_time_hours
FROM raw_events
WHERE event_type = 'deployment'
  AND payload->>'status' = 'success'
  AND occurred_at >= NOW() - INTERVAL '%s days';
-- Extract p50: SELECT approx_percentile(0.50, lead_time_hours) FROM above

-- FDRT (time from failed deploy to next successful deploy, same service)
-- Requires window function across deployment events ordered by occurred_at

-- Change Failure Rate
SELECT
  COUNT(*) FILTER (WHERE payload->>'status' IN ('failed','rollback')) * 100.0 / COUNT(*)
FROM raw_events
WHERE event_type = 'deployment'
  AND occurred_at >= NOW() - INTERVAL '%s days';

-- Rework Rate (user-visible only)
SELECT
  COUNT(r.*) * 100.0 / COUNT(DISTINCT d.id)
FROM raw_events d
LEFT JOIN raw_events r ON r.event_type = 'rework'
  AND r.payload->>'deployment_sha' = d.payload->>'commit_sha'
  AND (r.payload->>'user_visible')::boolean = true
WHERE d.event_type = 'deployment'
  AND d.occurred_at >= NOW() - INTERVAL '%s days';
```

**Acceptance Criteria**

- [ ] `compute/metrics.py` CLI: `python compute/metrics.py --window 30 --repo paruff/uFawkesObs`
- [ ] Writes result to `dora_snapshots` table
- [ ] Pushes Prometheus metrics via pushgateway:
      `dora_deployment_frequency_per_week`, `dora_lead_time_p50_hours`,
      `dora_lead_time_p95_hours`, `dora_fdrt_p50_hours`, `dora_cfr_pct`,
      `dora_rework_rate_pct`
- [ ] `proxy_metrics: true` flag set when `first_commit_at` unavailable (falls back
      to PR merge time as lead time proxy); flag propagated to `dora_snapshots`
- [ ] FDRT computed as deployment-gap, NOT incident-resolution gap (documented in
      inline comments with DORA 2025 citation)
- [ ] DORA tier thresholds from 2025 research applied per metric; each metric in output
      includes `dora_tier` field
- [ ] `tests/unit/test_metrics.py` — covers all five metrics with fixture data;
      includes FDRT edge cases (no recovery deployment in window → null, not error)
- [ ] GitHub Actions cron job: `.github/workflows/compute-metrics.yml` runs daily

**DORA capability:** AI Capability 2 + 7
**Blocks:** Issues 9, 10, 11, 12

---

**Issue 5**
`feat(collectors): GitHub Actions reusable workflows for deployment and PR events`
**Labels:** `feat`, `tier-1`, `phase-0`
**Estimate:** 1 session
**Depends on:** Issue 2

**Summary**
Reusable GitHub Actions workflows that any repo in the fawkes suite can call to emit
deployment events and PR events to the uFawkesDORA ingestion API. This is the
primary event source for GitHub-native teams.

**Context**
These workflows are called by other repos — they are not triggered internally.
A repo using uFawkesDORA adds one `uses:` line to its release workflow and immediately
starts emitting DORA events. Zero new tooling required.

**Acceptance Criteria**

- [ ] `collectors/github/dora-deployment-event.yml` — reusable workflow
      (`workflow_call`), inputs: `status`, `environment`, `pipeline_url`,
      `ai_assisted` (optional, default false); emits deployment-event to
      `${{ vars.DORA_INGESTION_URL }}/event`
- [ ] `collectors/github/dora-pr-event.yml` — reusable workflow; emits pr-event
      on PR merge including `first_commit_at` (oldest commit SHA timestamp in the PR,
      fetched via GitHub API)
- [ ] `collectors/github/README.md` — how to wire both workflows in 10 minutes:
      "add these 3 lines to your release workflow"
- [ ] `collectors/github/example-consumer.yml` — a complete example workflow showing
      both collector calls in context
- [ ] `tests/unit/test_github_collector.py` — validates schema compliance for
      sample GitHub webhook payloads (fixtures in `tests/acceptance/fixtures/`)
- [ ] Evidence: wire to uFawkesObs repo, trigger a test release → deployment event
      appears in `raw_events` table

**DORA capability:** AI Capability 2
**Blocks:** Issues 9, 12 (PR annotations need PR events)

---

**Issue 6**
`feat(collectors): generic webhook receiver + Woodpecker snippet + manual incident`
**Labels:** `feat`, `tier-1`, `phase-0`
**Estimate:** 1 session
**Depends on:** Issue 2

**Summary**
Three collector patterns for non-GitHub sources: a Woodpecker CI pipeline snippet,
a generic curl-based webhook pattern for any CI/CD system, and a manual incident
declaration template for teams without PagerDuty/Grafana OnCall.

**Context**
The ingestion API already accepts any well-formed event JSON (Issue 3). This issue
documents HOW to call it from specific sources — Woodpecker (uFawkesPipe), Portainer
(via webhook on stack redeploy), and manual incident declaration.

The manual incident pattern is critical: FDRT requires incident events. Teams without
a SaaS incident management tool should have a copy-paste curl command that takes 10
seconds to run.

**Acceptance Criteria**

- [ ] `collectors/woodpecker/pipeline-snippet.yml` — Woodpecker pipeline step
      that POSTs a deployment-event on pipeline success/failure; uses `from_secret` for
      `DORA_INGESTION_URL` and `DORA_API_KEY` (if auth enabled)
- [ ] `collectors/generic/curl-examples.sh` — curl commands for each event type
      (deployment success, deployment failed, incident opened, incident resolved, rework);
      well-commented, copy-paste ready
- [ ] `collectors/manual-incident/declare-incident.sh` — a script that prompts for
      `incident_id` and `service`, then POSTs the incident-event; engineers run this when
      paged; companion `resolve-incident.sh` for resolution
- [ ] `collectors/generic/README.md` — how to wire Portainer webhook (Portainer
      supports outgoing webhooks on stack redeploy — document the exact format)
- [ ] Evidence: run `declare-incident.sh` → incident event appears in `raw_events`

**DORA capability:** AI Capability 2
**Blocks:** Issue 10 (FDRT requires incident events)

---

**Issue 7**
`docs: README following uFawkes documentation standard`
**Labels:** `docs`, `tier-1`, `phase-0`
**Estimate:** 30 min
**No dependencies** (file this and start writing immediately)

**Summary**
uFawkesDORA has no README. Write one following the minimum standard from the
`documentation` skill: What This Is / What This Is Not / Status / Architecture /
Quick Start / Testing / DORA Capability / Contributing / Suite Context.

**Architecture section must explain the plane model**: uFawkesDORA is a stateless
compute plane that attaches to a resource plane Postgres instance. Link the architecture
diagram in this document.

**"What This Is Not" must explicitly state:**

- Not a team performance management tool or ranking system
- Not a replacement for uFawkesObs (which provides the instrumentation substrate)
- Not a way to measure or compare individual engineers
- Not a commercial alternative to LinearB/Swarmia — it is self-hosted and requires
  engineering effort to wire

**Acceptance Criteria**

- [ ] All 9 required sections present and not placeholder text
- [ ] Architecture diagram (ASCII or Mermaid) showing the two-plane model
- [ ] "Status" section honest about current state: "v0.0 — scaffold only.
      See roadmap for what's coming."
- [ ] Suite Context section with links to all 8 repos
- [ ] `docs-lint` CI check passes

---

### Phase 1 — Dashboards

---

**Issue 8**
`feat(dashboards): DORA Overview — five metrics with 2025 tier model`
**Labels:** `feat`, `tier-1`, `phase-1`
**Estimate:** 1-2 sessions
**Depends on:** Issues 3, 4, 5

**Summary**
The primary Grafana dashboard: five metrics, current value, 30-day trend, DORA 2025
tier overlays, team/service/window filters. Reads from BOTH Prometheus (time-series
panels) and Postgres (current snapshot + archetype hint).

**Two datasource approach:**

- Prometheus: time-series trend panels (uses derived metrics pushed by compute job)
- Postgres datasource plugin: current snapshot panel, FDRT stage breakdown table

**Acceptance Criteria**

- [ ] `dashboards/dora-overview.json` — Grafana provisioning JSON
- [ ] Five metric panels; each shows: stat (current value + tier badge), time-series
      (30/90 day trend), threshold lines (2025 DORA research values)
- [ ] FDRT panel uses Throughput framing (not "recovery time from incident") with
      inline annotation explaining the 2025 reclassification
- [ ] Rework Rate panel includes tooltip: "Only counts user-visible unplanned deployments"
- [ ] Dashboard variables: `team`, `service`, `environment`, `window` (7d/30d/90d)
- [ ] Banner when `proxy_metrics=true`: "⚠ Proxy metrics active — wire deployment
      events for accurate data. See collectors/README.md"
- [ ] Copy dashboard JSON to uFawkesObs `grafana/provisioning/dashboards/`
      directory (or document the copy step in the release checklist)
- [ ] Evidence: `docker compose up` with demo fixture data → all five panels show
      non-empty data; no Grafana errors in browser console

**DORA capability:** AI Capability 7

---

**Issue 9**
`feat(dashboards): Leading Indicators — early warning before metrics degrade`
**Labels:** `feat`, `tier-1`, `phase-1`
**Estimate:** 1 session
**Depends on:** Issues 3, 4, 5

**Summary**
The second dashboard: leading indicators that predict DORA metric degradation before
it happens — PR cycle time, branch age, CI duration trend, rework rate trend, and
(in the AI era) PR size trend as an AI adoption signal.

Each panel includes a one-line annotation: what degradation means and which lagging
DORA metric it will affect first.

**Leading indicators → lagging DORA metric they predict:**

| Leading indicator                      | Predicts                                  |
| -------------------------------------- | ----------------------------------------- |
| PR cycle time P90 > 24hrs              | Lead time increase                        |
| PR size lines-added 14-day MA climbing | Rework Rate increase (AI over-generation) |
| CI duration 7-day MA climbing          | Deployment frequency drop                 |
| Rework rate 14-day MA climbing         | CFR trajectory                            |
| Branch age P90 > 3 days                | Lead time increase + batch size violation |

**Acceptance Criteria**

- [ ] `dashboards/leading-indicators.json` — Grafana provisioning JSON
- [ ] All five leading indicator panels with annotation text
- [ ] PR size trend panel includes note: "AI-assisted PRs average 50-150% larger
      than baseline — monitor for Rework Rate correlation (DORA 2025)"
- [ ] Branch age panel note: limitation if GitHub API polling not available;
      alternative: use `pr-event` `opened_at` - `first_commit_at` as proxy

**DORA capability:** Core: Monitoring + AI Capability 5

---

**Issue 10**
`feat(alerts): regression-based Alertmanager rules (not threshold-based)`
**Labels:** `feat`, `tier-1`, `phase-1`
**Estimate:** 1 session
**Depends on:** Issue 4

**Summary**
Prometheus alerting rules that fire when a DORA metric degrades relative to its
30-day baseline — NOT when it crosses a fixed threshold. Static thresholds
("alert if CFR > 10%") are wrong because they penalize teams already performing
poorly and don't alert improving teams that reverse course.

Regression-based rules: "alert if this metric is significantly worse than YOUR
recent performance."

**Alert rules:**

```yaml
# alerts/dora-regression.yaml
groups:
  - name: dora_regression
    interval: 1h
    rules:
      - alert: DoraDeploymentFrequencyDrop
        expr: |
          (
            avg_over_time(dora_deployment_frequency_per_week[7d])
            / avg_over_time(dora_deployment_frequency_per_week[30d])
          ) < 0.70
        for: 24h
        labels:
          severity: warning
          category: dora_throughput
        annotations:
          summary: "Deployment frequency dropped >30% vs 30-day average"
          description: "{{ $labels.repo }} deploying {{ $value | humanize }}x/wk
            vs 30d avg. Check for blocked PRs or migration in progress."
          runbook_url: "https://github.com/paruff/uFawkesDORA/blob/main/docs/runbooks/deployment-frequency-drop.md"

      - alert: DoraFDRTSpike
        expr: |
          dora_fdrt_p50_hours
          > (avg_over_time(dora_fdrt_p50_hours[30d]) * 2)
        for: 6h
        labels:
          severity: critical
          category: dora_throughput
        annotations:
          summary: "FDRT doubled vs 30-day average — throughput at risk"
          description: "Recovery taking {{ $value }}hrs vs 30d avg.
            FDRT is a Throughput metric (DORA 2025) — this blocks re-deployment."
          runbook_url: "https://github.com/paruff/uFawkesDORA/blob/main/docs/runbooks/fdrt-spike.md"

      - alert: DoraCFRSpike
        expr: |
          dora_cfr_pct > (avg_over_time(dora_cfr_pct[30d]) + 5)
        for: 24h
        labels:
          severity: warning
          category: dora_stability
        annotations:
          summary: "Change Failure Rate +5 points above 30-day average"

      - alert: DoraReworkRateClimb
        expr: |
          dora_rework_rate_pct > (avg_over_time(dora_rework_rate_pct[30d]) + 3)
        for: 48h
        labels:
          severity: warning
          category: dora_stability
        annotations:
          summary: "Rework Rate climbing — possible AI over-generation effect"
          description: "Rework Rate at {{ $value }}% vs 30d avg.
            Per DORA 2025, Rework Rate is the primary AI quality signal.
            Check PR size trend in Leading Indicators dashboard."

      - alert: DoraLeadingIndicatorPRCycleTime
        expr: |
          histogram_quantile(0.90, rate(dora_pr_cycle_time_seconds_bucket[7d])) / 3600 > 24
        for: 72h
        labels:
          severity: warning
          category: leading_indicator
        annotations:
          summary: "PR cycle time P90 exceeds 24hrs for 72hrs"
          description: "Leading indicator: Lead Time will increase if not addressed."
```

**Acceptance Criteria**

- [ ] `alerts/dora-regression.yaml` — all five regression alerts above
- [ ] `alerts/leading-indicator.yaml` — PR cycle time + PR size trend alerts
- [ ] Each alert has `summary`, `description` (with current value and context),
      `runbook_url` linking to a docs/runbooks/ file (stub is fine for v0.1)
- [ ] `tests/unit/test_alert_rules.py` uses `promtool test rules` with synthetic
      data: each alert fires on degraded data, does NOT fire on healthy data
- [ ] Alerts wired to Alertmanager in uFawkesObs via `docker-compose.yml` network

**DORA capability:** Core: Monitoring + AI Capability 7
**Blocks:** Issue 13 (Slack notifications triggered by these alerts)

---

### Phase 2 — Beyond Dashboards

---

**Issue 11**
`feat(compute): seven archetype classifier with wellbeing integration`
**Labels:** `feat`, `tier-2`, `phase-2`
**Estimate:** 2 sessions
**Depends on:** Issue 4

**Summary**
Implement `compute/archetype.py` — classify a team/repo into one of the seven 2025
DORA archetypes using delivery metrics from `dora_snapshots` AND optional wellbeing
scores from `wellbeing_surveys`. Store classification in `archetype_history`.

This is the most strategically differentiated feature in the suite — no open-source
DORA tool correctly implements the seven archetypes as of mid-2026.

**Acceptance Criteria**

- [ ] `compute/archetype.py` inputs: repo name + optional quarter string
      (pulls from `dora_snapshots` and `wellbeing_surveys` automatically)
- [ ] Returns: `{"archetype": "Pragmatic performers", "confidence": 0.78,
"wellbeing_data": false, "primary_bottleneck": "review_cycle_time",
"recommendations": ["...", "..."]}`
- [ ] When `wellbeing_surveys` has no data for the period: returns metrics-only
      classification with `confidence` capped at 0.65 and `wellbeing_data: false`
- [ ] Classification logic documented inline — not a black box; cites DORA 2025
      archetype definitions for each decision boundary
- [ ] Writes result to `archetype_history` table
- [ ] `compute/archetype_survey.md` — four-question quarterly wellbeing survey
      with a curl command to POST results to the ingestion API as a structured event
      (maps to `wellbeing_surveys` table)
- [ ] `tests/unit/test_archetype.py` — covers all seven archetypes with
      representative fixture data; tests confidence degradation without wellbeing data
- [ ] Scheduled via `.github/workflows/compute-archetype.yml` (monthly, after
      `compute-metrics.yml` runs)

**DORA capability:** AI Capability 6 + 7
**Blocks:** Issue 12 (archetype dashboard)

---

**Issue 12**
`feat(dashboards): Archetype Profile + AI Impact dashboards`
**Labels:** `feat`, `tier-2`, `phase-2`
**Estimate:** 2 sessions
**Depends on:** Issues 4, 11

**Summary**
Two dashboards in one issue because they share a datasource pattern (both read
primarily from Postgres via Grafana Postgres datasource plugin):

**Archetype Profile:** Team's current archetype, confidence, radar chart of five
metrics vs archetype centroid, two specific recommendations, link to wellbeing survey.

**AI Impact:** PR size trend vs deployment frequency, code churn rate, Rework Rate
vs Deployment Frequency scatter, FDRT trend with AI adoption overlay. First open-source
dashboard to specifically answer "are we faster but messier?"

**Acceptance Criteria — Archetype Profile**

- [ ] `dashboards/archetype-profile.json`
- [ ] Archetype name stat panel (prominent)
- [ ] Radar chart: five metrics normalized 0-1, overlaid with archetype centroid
- [ ] Confidence stat panel with colour: green (≥0.75), yellow (0.5-0.75), red (<0.5)
- [ ] "Confidence limited — no wellbeing survey data" text panel when confidence < 0.65
- [ ] Two recommendation text panels keyed to archetype (static text; no LLM calls)
- [ ] Link to `compute/archetype_survey.md`

**Acceptance Criteria — AI Impact**

- [ ] `dashboards/ai-impact.json`
- [ ] PR size 14-day MA panel with DORA 2025 reference annotation
      ("AI inflates PR size 50-150% — monitor Rework Rate for quality signal")
- [ ] Rework Rate vs Deployment Frequency time series (dual-axis): "faster but messier" quadrant
- [ ] Code churn rate panel (lines changed within 14 days of original commit / total lines)
- [ ] FDRT trend panel
- [ ] `ai_assisted` annotation line when available

**DORA capability:** AI Capability 3 + 5 + 6

---

**Issue 13**
`feat(notifications): weekly Slack digest + regression alerts to Slack`
**Labels:** `feat`, `tier-2`, `phase-2`
**Estimate:** 1-2 sessions
**Depends on:** Issues 4, 10

**Summary**
Two notification channels in one issue: the weekly summary digest (proactive, scheduled)
and Slack routing for regression alerts (reactive, triggered by Alertmanager).

**Context**
This is the highest-behavioural-impact feature based on commercial tooling analysis.
Teams that receive a weekly digest act on it. Teams that have a Grafana dashboard
they could open don't. The digest makes DORA metrics unavoidable without being
surveillance-like — it's a team tool, not a management reporting tool.

**Acceptance Criteria — Weekly Digest**

- [ ] `notifications/digest/generate_digest.py` — queries latest `dora_snapshots`
      from Postgres, produces structured weekly digest
- [ ] Digest content (per repo): five metrics current vs prior week, ✅/⚠️/❌ per
      metric, one "Focus this week" recommendation (worst-trending metric), Grafana link
- [ ] Markdown output: `notifications/digest/weekly-digest-YYYY-WW.md`
- [ ] `notifications/slack/slack_webhook.py` — posts digest to `SLACK_WEBHOOK_URL`;
      gracefully skips with logged warning if not configured
- [ ] `.github/workflows/weekly-digest.yml` — runs Monday 8am UTC; manual dispatch
      also supported

**Acceptance Criteria — Alert Routing**

- [ ] Alertmanager `receivers:` block in uFawkesObs routes `dora_regression`
      and `leading_indicator` alerts to a `DORA_SLACK_WEBHOOK_URL` distinct from
      other alert channels (engineering teams want DORA alerts separate from infra alerts)
- [ ] Alert Slack message format: metric name, current value, 30d baseline, trend
      emoji, runbook link — NOT a wall of text
- [ ] Evidence: inject a metric regression via synthetic Prometheus data →
      alert fires → Slack message received within 5 minutes

**DORA capability:** Core: Monitoring + AI Capability 7

---

**Issue 14**
`feat(notifications): PR-level lead time annotation`
**Labels:** `feat`, `tier-2`, `phase-2`
**Estimate:** 1 session
**Depends on:** Issues 3, 5

**Summary**
Post a comment on every merged PR with its lead time contribution vs team baseline.
The metric is most actionable at the point of work, not on a dashboard.

**Acceptance Criteria**

- [ ] `notifications/pr_annotation/annotate.py` — reads PR event from Postgres,
      computes this PR's lead time, queries 30d P50 baseline, generates comment
- [ ] `.github/workflows/dora-pr-annotation.yml` — reusable workflow, runs on PR merge
- [ ] Comment format: lead time for this PR, team 30d P50, emoji (🚀 if faster,
      ⏱️ if slower), one-line note if >2x P50 ("consider breaking this into smaller PRs")
- [ ] If `ai_assisted: true`: adds "AI-assisted PR: lead time vs baseline tracked
      for AI impact dashboard"
- [ ] Disabled via `DORA_PR_ANNOTATIONS: "false"` repo variable
- [ ] Posted by `github-actions[bot]`, not a personal token

**DORA capability:** AI Capability 5 + Core: Version control

---

**Issue 15**
`feat(compute): value stream indicators — stage-level lead time breakdown`
**Labels:** `feat`, `tier-3`, `phase-2`
**Estimate:** 2 sessions
**Depends on:** Issues 3, 5, 4

**Summary**
Implement `compute/vsi.py` — Value Stream Indicators that segment lead time into
five stages (coding, review, CI, deploy, rework) and identify which stage is the
constraint. The 2025 DORA research names VSM as the diagnostic layer above the five
delivery metrics — it answers "where are AI productivity gains being absorbed?"

**Acceptance Criteria**

- [ ] `compute/vsi.py` — queries `raw_events` for pr-events and deployment-events,
      reconstructs stage durations for each commit-to-deploy journey
- [ ] Writes to `vsi_stage_breakdown` table
- [ ] Computes: value-add time (coding + CI + deploy), wait time (review + queue),
      VSM efficiency % (value-add / total)
- [ ] Identifies primary bottleneck (highest wait time stage) with repo-level output
- [ ] `dashboards/value-stream.json` — Grafana dashboard showing stage breakdown
      waterfall + bottleneck highlight + efficiency trend
- [ ] `tests/unit/test_vsi.py` with representative event fixture sequences

**DORA capability:** AI Capability 2 + 7 + VSM (2025 DORA research)

---

### Phase 3 — Dojo

---

**Issue 16**
`docs(dojo): Yellow Belt module — "Wire your first DORA event in 60 minutes"`
**Labels:** `docs`, `dojo`, `tier-2`, `phase-3`
**Estimate:** 2 sessions
**Depends on:** Issue 8

**Summary**
The Dojo module that takes a learner from "uFawkesDORA running locally" to "my
deployment frequency is visible in Grafana" in one session. This is the primary
onboarding and marketing asset for the repo.

**Acceptance Criteria**

- [ ] 7-section gold standard per `dojo-module` skill
- [ ] Deliverable: "Deployment Frequency panel shows at least 3 real events"
- [ ] Evidence artifact: screenshot of DORA Overview dashboard with non-zero
      Deployment Frequency + Grafana URL
- [ ] Automated validator: `docs/dojo/yellow-belt/validators/dora-module-validator.sh`
      — checks Grafana API for non-empty deployment frequency panel
- [ ] `lab_verified` date set; works on Mac ARM and Linux x86 from clean clone
- [ ] DORA citation in "Why This Matters": references 2025 "five metrics" evolution

---

## Part 6: Revised Milestone Sequencing

At 2hrs/day with uFawkesObs v0.1.0 as the first priority this week:

**This week (alongside Obs release):**
Issue 7 (README — 30 min, zero risk, file now)

**Week 2:**
Issue 1 (database schema) + Issue 2 (event schemas) — these can run in parallel
as they have no dependencies on each other.

**Week 3:**
Issue 3 (ingestion API + queue) — unblocks the entire collector layer.

**Week 4:**
Issues 5 + 6 (collectors: GitHub Actions + generic/Woodpecker/manual incident) + Issue 4 (compute: five metrics) — first data flowing end-to-end.

**Week 5:**
Issue 8 (DORA Overview dashboard) + Issue 10 (regression-based alerts).
**This is the v0.1.0 release candidate.**

**First dev.to post (Week 5):**
"uFawkesDORA v0.1: self-hosted DORA metrics that alert you when you're regressing —
not when you cross someone else's threshold"

The hook: regression-based alerting (alert relative to YOUR baseline, not a
static number) doesn't exist in any open-source DORA tool. That's the
differentiating paragraph.

**Week 6:**
Issue 9 (Leading Indicators dashboard). v0.1.1 release.

**Weeks 7-8:**
Issue 11 (archetype classifier) + Issue 12 (Archetype + AI Impact dashboards).
**v0.2.0 release — the feature no open-source tool has.**

**Weeks 9-10:**
Issues 13 (digest + Slack) + Issue 14 (PR annotations). v0.2.1 release.

**Phase 3 (when Dojo Phase 2 begins):**
Issues 15 (VSM) + Issue 16 (Dojo module).

---

## Known limitations and documented ceilings

| Limitation                                                   | Impact                                            | Acceptable until                                     |
| ------------------------------------------------------------ | ------------------------------------------------- | ---------------------------------------------------- |
| Event queue: Postgres SKIP LOCKED                            | ~500 events/second max                            | >10 repos, >100 deploys/day                          |
| FDRT requires explicit incident events                       | Teams without incident tooling undercount FDRT    | Manual curl workaround in Issue 6                    |
| Archetype classifier: metrics-only confidence capped at 0.65 | Wellbeing survey required for full classification | Quarterly survey cadence per platform-feedback skill |
| Grafana Postgres plugin: read-only queries only              | No real-time data in Postgres-sourced panels      | Prometheus covers real-time; Postgres for historical |
| TimescaleDB: adds upgrade complexity vs vanilla Postgres     | Slightly harder to troubleshoot                   | Accepted tradeoff for time-series query performance  |
