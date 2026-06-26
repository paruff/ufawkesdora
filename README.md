# uFawkesDORA

[![CI](https://github.com/paruff/ufawkesdora/actions/workflows/ci.yml/badge.svg)](https://github.com/paruff/ufawkesdora/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## What This Is

uFawkesDORA is an open-source DORA metrics pipeline that collects delivery events from any CI/CD system, computes the five DORA 2025 metrics (Deployment Frequency, Lead Time for Changes, Failed Deployment Recovery Time, Change Failure Rate, Rework Rate), and classifies teams against the DORA seven-archetype model. It is designed for platform engineering teams who want to measure and improve their delivery performance using the [DORA 2025 framework](https://dora.dev).

See the [full specification](docs/spec/specification.md) for detailed metric definitions, event schema contracts, computation rules, alerting specifications, and wellbeing survey design.

## What This Is Not

- **Not a team performance management tool or ranking system.** DORA metrics are a health indicator for your delivery process, not a scorecard for individuals or teams.
- **Not a replacement for uFawkesObs.** uFawkesObs provides the observability substrate (OTel, Prometheus, Grafana, Loki) that uFawkesDORA builds on. uFawkesDORA is a narrow compute layer, not an observability platform.
- **Not a way to measure or compare individual engineers.** DORA metrics measure system-level outcomes. Comparing individuals on these metrics is an anti-pattern that undermines the methodology.
- **Not a commercial alternative to LinearB or Swarmia.** This is a self-hosted, DIY tool. It requires engineering effort to wire into your CI/CD pipelines and infrastructure. There is no SaaS offering, no support SLA, and no UI beyond what you build on top of it.

## Status

**v0.0 — scaffold only.** The schema, ingestion API, event schemas, metrics computation, five DORA 2025 metrics, and collector patterns exist. What is built for v0.1.0:

- ✅ Five DORA metrics computed from Postgres event store (Deployment Frequency, Lead Time for Changes, FDRT, CFR, Rework Rate)
- ✅ Ingestion API with JSON Schema validation (events: `deployment`, `incident`, `pr`, `rework`)
- ✅ Async worker with `SKIP LOCKED` dequeuing
- ✅ GitHub Actions collectors for deployment and PR events
- ✅ Generic webhook receiver for Woodpecker/Portainer/other sources
- ✅ Manual incident declaration script
- ✅ Regression-based Prometheus alerting rules
- ✅ README following uFawkes documentation standard

**In scope for v0.1.0 (not yet built):**
- Grafana DORA Overview dashboard (dual datasource: Prometheus + Postgres)
- Leading indicators dashboard (PR cycle time, PR size MA, Rework Rate MA)
- Weekly Slack digest (`notifications/digest/generate_digest.py`)
- PR-level lead time annotations (GitHub Actions reusable workflow)

**In scope for v0.2.0:**
- Seven-archetype classifier with wellbeing survey
- Archetype Profile dashboard and AI Impact dashboard
- Value stream indicators (Lead Time by stage)
- Production deployment guide
- Automated schema migration in CI

**Explicitly out of scope (uFawkesDORA is not):**
- A Kubernetes/cluster instrumentation tool — uFawkesObs handles infrastructure observability
- An individual developer metrics system — DORA measures system outcomes, not people
- A real-time streaming pipeline — all computation is batch
- A multi-tenant platform — self-hosted for single teams
- An SLA/SLO tracker — that is an uFawkesObs reliability concern

See the [uFawkes roadmap](https://github.com/paruff/fawkes/blob/main/ROADMAP.md) for the full picture.

## Architecture

uFawkesDORA follows a **two-plane model**: a stateless compute plane that attaches to a stateful resource plane (PostgreSQL + TimescaleDB).

```mermaid
flowchart LR
    subgraph Resource Plane
        TSDB[(TimescaleDB\nPostgreSQL + Hypertables)]
    end

    subgraph Compute Plane
        API[Ingestion API\nFastAPI + asyncpg]
        WKR[Worker\nAsync event processor]
        MET[Compute Engine\nDORA metrics + Pushgateway]
        ARCH[Archetype Classifier\n7-archetype model]
        DIGEST[Delivery\nDashboards + Digest + PR annotations]

        COLL1[GitHub Collectors\nReusable workflows]
        COLL2[Non-GitHub Collectors\nShell / curl / Woodpecker]

        COLL1 -->|POST /event| API
        COLL2 -->|POST /event| API
        API -->|INSERT| TSDB
        WKR -->|SKIP LOCKED dequeue| TSDB
        MET -->|TimescaleDB queries| TSDB
        MET -->|Pushgateway| PROM[(Prometheus\nin uFawkesObs)]
        ARCH -->|read snapshots| TSDB
        DIGEST -->|read snapshots| TSDB
        DIGEST -->|Grafana| PROM
    end

    style TSDB fill:#2d5a27,color:#fff
    style API fill:#1a5276,color:#fff
    style WKR fill:#1a5276,color:#fff
    style MET fill:#1a5276,color:#fff
    style ARCH fill:#1a5276,color:#fff
    style DIGEST fill:#1a5276,color:#fff
    style COLL1 fill:#633974,color:#fff
    style COLL2 fill:#633974,color:#fff
```

### Data flow

1. **Collectors** (GitHub reusable workflows, Woodpecker CI steps, shell scripts, curl) POST canonical events to the ingestion API. Four event types are supported: `deployment`, `incident`, `pr`, and `rework`.
2. **Ingestion API** validates the event against its JSON Schema (`events/*.schema.json`), enqueues it with status `pending`.
3. **Worker** dequeues events via `SELECT ... FOR UPDATE SKIP LOCKED`, validates payload structure, inserts into `raw_events`.
4. **Compute Engine** (cron or triggered) queries `raw_events` for each team, computes the five DORA 2025 metrics (Deployment Frequency, Lead Time for Changes, FDRT, Change Failure Rate, Rework Rate), and writes a snapshot to `dora_snapshots`. Optionally pushes metrics to a Prometheus Pushgateway for Grafana dashboards.
5. **Archetype Classifier** reads the latest snapshots and classifies the team against the DORA seven-archetype model (Harmonious high-achievers, Pragmatic performers, Stable and methodical, Constrained by process, Legacy bottleneck, High impact/low cadence, plus a seventh archetype pending primary-source confirmation). Classification confidence is capped when no wellbeing survey data is available.
6. **Delivery mechanisms** surface results: Grafana dashboards (Prometheus + Postgres datasources), weekly Markdown digest, and PR-level lead time annotations.

### Key metric definitions

- **FDRT (Failed Deployment Recovery Time)**: Time from a failed deployment to the next successful deployment of the same service — **not** incident-resolution MTTR. FDRT was reclassified from Stability to Throughput in the 2025 DORA model. It is never called "MTTR" anywhere in the system.
- **Rework Rate**: Percentage of deployments that are unplanned fixes for user-visible issues from a recent deployment. This is the primary signal for AI-assisted development quality — AI-generated code with higher churn pushes Rework Rate up before CFR spikes.

### Repo structure

```
├── collectors/            # Event collectors
│   ├── github/            #   Reusable GitHub Actions workflows
│   ├── woodpecker/        #   Woodpecker CI pipeline snippet
│   ├── generic/           #   curl examples, per-platform env var mappings
│   └── manual-incident/   #   declare-incident.sh + resolve-incident.sh
├── compute/               # DORA metrics computation engine
├── database/
│   ├── init/              #   Idempotent init scripts (00, 01, 02)
│   ├── migrations/        #   Forward-only numbered migrations (001-003)
│   └── timescaledb/       #   Hypertable conversion SQL
├── docs/                  # Planning & discovery artifacts
│   ├── spec/              #   Product specification (metrics, schemas, alerts)
│   ├── design/            #   Technical designs
│   ├── plan/              #   Task plans and decomposition
│   └── discovery/         #   User research discovery briefs
├── events/                # Canonical event JSON Schemas (Draft-07)
├── ingestion/
│   ├── api/               #   FastAPI ingestion endpoint
│   └── processor/         #   Async worker with SKIP LOCKED
└── tests/
    ├── unit/              # Fast unit tests (no Docker needed)
    └── integration/       # Integration tests (require testcontainers)
```

## Quick Start

### Prerequisites

- Python 3.11+
- Docker (for TimescaleDB and integration tests)
- `uv` or `pip`

### 1. Clone and install

```bash
git clone https://github.com/paruff/ufawkesdora.git
cd ufawkesdora
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-ingestion.txt -r compute/requirements.txt
```

### 2. Start TimescaleDB

```bash
cp .env.example .env
# Edit .env: uncomment POSTGRES_PASSWORD and set a strong password
export POSTGRES_PASSWORD=$(openssl rand -base64 18)
docker compose -f docker-compose.dev.yml up -d
```

### 3. Run unit tests

```bash
make test-unit
```

All 100+ unit tests complete in ~3 seconds. No Docker required.

### 4. Run the ingestion API

```bash
export DATABASE_URL="postgresql://dora_app:${POSTGRES_PASSWORD}@localhost:5432/dora_metrics"
uvicorn ingestion.api.main:app --port 8088
```

### 5. Send a test event

```bash
curl -s -X POST http://localhost:8088/event \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": "1.0",
    "event_type": "deployment",
    "repo": "my-org/my-service",
    "service": "my-service",
    "team_id": "my-team",
    "environment": "production",
    "status": "success",
    "occurred_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"
  }'
```

Expected response: `HTTP 201`

### 6. Declare an incident (manual collector)

```bash
export DORA_INGESTION_URL=http://localhost:8088
./collectors/manual-incident/declare-incident.sh \
  --incident_id=INC-001 \
  --service=my-service \
  --severity=critical
```

## Testing

| Tier        | Command                 | Requires Docker | Approx. time |
| ----------- | ----------------------- | --------------- | ------------ |
| Unit        | `make test-unit`        | No              | ~3 s         |
| Integration | `make test-integration` | Yes             | ~30 s        |
| All         | `make test-all`         | Mixed           | ~35 s        |
| Coverage    | `make test-coverage`    | No              | ~5 s         |

Unit tests cover:

- Schema validation (17 tests — all table constraints, role grants, hypertables)
- Event schema validation (46 tests — valid/invalid payloads, cross-schema rejection, ISO 8601)
- Ingestion API (13 tests — enqueue, batch, validation, health)
- Worker (12 tests — dequeue, retry, error handling)
- Metrics computation (33 tests — all five DORA metrics, tier thresholds, pushgateway)
- GitHub collector transformations (17 tests — webhook → canonical event, field mapping)

## DORA Capability

uFawkesDORA implements **DORA AI Capability 2: DORA metrics pipeline** — automated collection and computation of the five DORA 2025 metrics (Deployment Frequency, Lead Time for Changes, Failed Deployment Recovery Time, Change Failure Rate, Rework Rate). It also contributes to **DORA AI Capability 7: Quality internal platforms** — the measurement half — by providing the metric substrate that platform teams use to validate whether their IDP improvements are actually moving the needle.

**Key design choices, aligned with the [specification](docs/spec/specification.md):**

- **Automated**: Collectors fire automatically from CI pipelines (GitHub Actions, Woodpecker, curl webhooks). No manual data entry.
- **Canonical schemas**: All events validated against Draft-07 JSON Schemas with `additionalProperties: false` — prevents data quality drift.
- **DORA 2025**: Implements the 2025 framework including FDRT reclassified as a Throughput metric (not incident MTTR) and Rework Rate as the fifth metric.
- **Seven-archetype classifier**: Teams are classified against the DORA 2025 seven-archetype model, not the deprecated Elite/High/Medium/Low tiers. Classification confidence is capped without wellbeing survey data.
- **Delivery surface**: Grafana dashboards (dual datasource — Prometheus for time series, Postgres for snapshots), weekly Markdown digest, and PR-level lead time annotations.
- **Regression-based alerts**: All DORA alerts are relative to a team's own 30-day baseline, not fixed industry thresholds.

**Leading indicators (v0.1.0):** PR cycle time P90, PR size 14-day MA, and Rework Rate 14-day MA predict metric degradation before it appears in the five DORA metrics.

**Value stream indicators (v0.2.0):** Lead Time segmented into coding, review, CI, deploy, and rework stages to identify where AI productivity gains are being absorbed.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow, coding standards, and pull request process.

Key points:

- All commits must follow [Conventional Commits](https://www.conventionalcommits.org/)
- Pre-commit is enforced in CI (`pre-commit run --all-files`)
- Unit tests must never require Docker
- Event schema changes require a version bump in the schema file

## Suite Context

This repo is part of the [uFawkes platform suite](https://ufawkes.dev).

| Repo                                                 | Purpose                                                   |
| ---------------------------------------------------- | --------------------------------------------------------- |
| [fawkes](https://github.com/paruff/fawkes)           | Core IDP — orchestrates the full platform                 |
| [uFawkesObs](https://github.com/paruff/uFawkesObs)   | Observability substrate (OTel, Prometheus, Grafana, Loki) |
| [uFawkesPipe](https://github.com/paruff/uFawkesPipe) | Lightweight CI/CD (Woodpecker + Portainer)                |
| [uFawkesDevX](https://github.com/paruff/uFawkesDevX) | Developer experience (CDE, golden paths)                  |
| [uFawkesDORA](https://github.com/paruff/uFawkesDORA) | DORA metrics and dashboards                               |
| [uFawkesSec](https://github.com/paruff/uFawkesSec)   | Security posture (policy-as-code)                         |
| [uFawkesAI](https://github.com/paruff/uFawkesAI)     | AI agent and skill suite                                  |
| [uFawkes.dev](https://ufawkes.dev)                   | Documentation and learning (Dojo)                         |

**Roadmap:** [fawkes/ROADMAP.md](https://github.com/paruff/fawkes/blob/main/ROADMAP.md)

## License

[MIT](LICENSE) — see [LICENSE](LICENSE) for the full text.
