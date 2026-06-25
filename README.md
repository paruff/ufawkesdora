# uFawkesDORA

[![Pipeline](https://github.com/paruff/ufawkesdora/actions/workflows/pipeline.yml/badge.svg)](https://github.com/paruff/ufawkesdora/actions/workflows/pipeline.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## What This Is

uFawkesDORA is an open-source DORA metrics pipeline that collects deployment and incident events, computes the four DORA metrics (Deployment Frequency, Lead Time, Change Failure Rate, Time to Restore), and classifies teams into DORA archetypes (elite, high, medium, low). It is designed for platform engineering teams who want to measure and improve their delivery performance using the [DORA 2025 framework](https://dora.dev).

## What This Is Not

- **Not a team performance management tool or ranking system.** DORA metrics are a health indicator for your delivery process, not a scorecard for individuals or teams.
- **Not a replacement for uFawkesObs.** uFawkesObs provides the observability substrate (OTel, Prometheus, Grafana, Loki) that uFawkesDORA builds on. uFawkesDORA is a narrow compute layer, not an observability platform.
- **Not a way to measure or compare individual engineers.** DORA metrics measure system-level outcomes. Comparing individuals on these metrics is an anti-pattern that undermines the methodology.
- **Not a commercial alternative to LinearB or Swarmia.** This is a self-hosted, DIY tool. It requires engineering effort to wire into your CI/CD pipelines and infrastructure. There is no SaaS offering, no support SLA, and no UI beyond what you build on top of it.

## Status

**v0.0 — scaffold only.** The schema, ingestion API, event schemas, metrics computation, and collector patterns exist. What is not yet built:

- Dynamic config reload (all config is file-based today)
- Grafana dashboards for the four DORA metrics
- Team CRUD API (teams are hardcoded in config)
- Automated schema migration in CI (migrations exist but must be applied manually)
- Production deployment guide

See the [uFawkes roadmap](https://github.com/paruff/fawkes/blob/main/ROADMAP.md) for what is coming next.

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

        COLL1[GitHub Collectors\nReusable workflows]
        COLL2[Non-GitHub Collectors\nShell / curl / Woodpecker]

        COLL1 -->|POST /event| API
        COLL2 -->|POST /event| API
        API -->|INSERT| TSDB
        WKR -->|SKIP LOCKED dequeue| TSDB
        MET -->|TimescaleDB queries| TSDB
        MET -->|Pushgateway| PROM[(Prometheus\nin uFawkesObs)]
    end

    style TSDB fill:#2d5a27,color:#fff
    style API fill:#1a5276,color:#fff
    style WKR fill:#1a5276,color:#fff
    style MET fill:#1a5276,color:#fff
    style COLL1 fill:#633974,color:#fff
    style COLL2 fill:#633974,color:#fff
```

### Data flow

1. **Collectors** (GitHub reusable workflows, Woodpecker CI steps, shell scripts, curl) POST canonical events to the ingestion API.
2. **Ingestion API** validates the event against its JSON Schema (`events/*.schema.json`), enqueues it with status `pending`.
3. **Worker** dequeues events via `SELECT ... FOR UPDATE SKIP LOCKED`, validates payload structure, inserts into `raw_events`.
4. **Compute Engine** (cron or triggered) queries `raw_events` for each team, computes the four DORA metrics + Rework Rate, classifies the team, and writes a snapshot to `dora_snapshots`. Optionally pushes metrics to a Prometheus Pushgateway for Grafana dashboards.

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
│   ├── spec/              #   Feature specifications
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

uFawkesDORA implements **DORA AI Capability 2: DORA metrics pipeline** — automated collection and computation of the four DORA metrics (Deployment Frequency, Lead Time, Change Failure Rate, Time to Restore) plus Rework Rate (DORA 2025). It also contributes to **DORA AI Capability 7: Quality internal platforms** — the measurement half — by providing the metric substrate that platform teams use to validate whether their IDP improvements are actually moving the needle.

- **Automated**: Collectors fire automatically from CI pipelines (GitHub Actions, Woodpecker, curl webhooks). No manual data entry.
- **Canonical schemas**: All events validated against Draft-07 JSON Schemas with `additionalProperties: false` — prevents data quality drift.
- **DORA 2025**: Implements the updated DORA 2025 framework including Rework Rate and FDRT (deployment-gap based Failure Deployment Recovery Time, not incident MTTR).

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
