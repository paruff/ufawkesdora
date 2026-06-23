# Design: Resource Plane Postgres Schema with TimescaleDB

## Architecture Overview

The data layer for uFawkesDORA follows a **schema-as-code** pattern. All database definitions live in the uFawkesDORA repository as version-controlled SQL scripts. These scripts are bind-mounted into the fawkes resource plane Postgres container at initialization time.

```
uFawkesDORA repo (this repo)
  │
  ├── database/init/          # Idempotent init scripts (00, 01, 02)
  ├── database/timescaledb/   # Hypertable conversion
  ├── database/migrations/    # Forward-only numbered migrations
  ├── docker-compose.dev.yml  # Local dev TimescaleDB
  │
  └── bind-mount ──► fawkes resource plane container
                        └── dora_metrics database
                              ├── event_queue
                              ├── raw_events (hypertable)
                              ├── dora_snapshots (hypertable)
                              ├── archetype_history
                              ├── wellbeing_surveys
                              └── vsi_stage_breakdown (hypertable)
```

Execution order on init:

1. `00-create-databases.sh` — creates databases + roles
2. `01-dora-schema.sql` — creates tables
3. `02-dora-roles.sql` — grants least-privilege permissions
4. `hypertables.sql` — converts time-series tables to hypertables

## Components

### Component: Database Init Scripts (`database/init/`)

| File                     | Purpose                                                              | Idempotent                                                             | Key behavior                                                                                                                                      |
| ------------------------ | -------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `00-create-databases.sh` | Create `dora_metrics`, `infisical`, `defectdojo` databases and roles | ✅ `CREATE DATABASE IF NOT EXISTS` via psql                            | Uses `DO $$ BEGIN ... EXCEPTION WHEN duplicate_database THEN null; END $$` pattern. No env vars for credentials.                                  |
| `01-dora-schema.sql`     | Create all 6 tables with columns, types, indexes                     | ✅ `CREATE TABLE IF NOT EXISTS`                                        | Defines the full schema per data model below                                                                                                      |
| `02-dora-roles.sql`      | Create `dora_app` role with least-privilege grants                   | ✅ `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object THEN null; END $$` | Grants only: INSERT on event_queue, SELECT/INSERT on raw_events/dora_snapshots, SELECT on archetype_history/wellbeing_surveys/vsi_stage_breakdown |

### Component: TimescaleDB Hypertables (`database/timescaledb/`)

| File              | Purpose                                                                                              |
| ----------------- | ---------------------------------------------------------------------------------------------------- |
| `hypertables.sql` | Converts `raw_events`, `dora_snapshots`, `vsi_stage_breakdown` to hypertables with time partitioning |

Hypertable strategy:

- Partition key: `recorded_at` (timestamptz)
- Chunk interval: 1 day (suitable for per-deployment granularity)
- Compression policy: enabled after 7 days

### Component: Migrations (`database/migrations/`)

| File                     | Purpose                                                                                                          |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| `001-initial-schema.sql` | Forward-only migration matching init scripts. Creates a `_migrations` tracking table. First run = migration 001. |

Migration strategy:

- Tracking table: `_schema_migrations` (version, applied_at, checksum)
- Forward-only: no rollback scripts
- Each migration is a single file with version prefix

### Component: Development Environment (`docker-compose.dev.yml`)

Single service: `timescaledb` on port 5432 with:

- Image: `timescale/timescaledb:latest-pg16`
- Init scripts mounted to `/docker-entrypoint-initdb.d/`
- Named volume for data persistence
- `.env` file for credentials (gitignored)

### Component: Tests (`tests/unit/test_schema.py`)

Test strategy:

- Uses `testcontainers.postgres` with `PostgresContainer` image `timescale/timescaledb:latest-pg16`
- Applies all init scripts in order
- Verifies: all 6 tables exist, 3 hypertables created, role permissions correct (not superuser)
- Cleans up container after run

## Data Model

### `event_queue`

Event ingestion buffer — incoming CI/CD events land here before processing.

| Column       | Type         | Constraints       | Description                                         |
| ------------ | ------------ | ----------------- | --------------------------------------------------- |
| id           | BIGSERIAL    | PRIMARY KEY       | Auto-incrementing ID                                |
| event_type   | VARCHAR(64)  | NOT NULL          | e.g., 'deployment', 'build', 'test_run'             |
| source       | VARCHAR(128) | NOT NULL          | Origin system (e.g., 'github-actions', 'gitlab-ci') |
| payload      | JSONB        | NOT NULL          | Event-specific data                                 |
| status       | VARCHAR(32)  | DEFAULT 'pending' | 'pending', 'processing', 'done', 'error'            |
| received_at  | TIMESTAMPTZ  | DEFAULT NOW()     | When event was ingested                             |
| processed_at | TIMESTAMPTZ  | NULL              | When event was processed                            |

Index: `(status, received_at)` for queue polling.

### `raw_events` (hypertable)

Processed deployment/CI events — the primary source for DORA metric computation.

| Column           | Type         | Constraints                | Description                      |
| ---------------- | ------------ | -------------------------- | -------------------------------- |
| id               | BIGSERIAL    | PRIMARY KEY                | Auto-incrementing ID             |
| event_queue_id   | BIGINT       | REFERENCES event_queue(id) | Source queue entry               |
| event_type       | VARCHAR(64)  | NOT NULL                   | e.g., 'deployment', 'build'      |
| source           | VARCHAR(128) | NOT NULL                   | Origin system                    |
| outcome          | VARCHAR(32)  | NOT NULL                   | 'success', 'failure', 'rollback' |
| duration_seconds | INTEGER      | NULL                       | Event duration                   |
| metadata         | JSONB        | NULL                       | Additional context               |
| recorded_at      | TIMESTAMPTZ  | NOT NULL DEFAULT NOW()     | When event occurred              |
| ingested_at      | TIMESTAMPTZ  | DEFAULT NOW()              | When record was created          |

Partitioned by: `recorded_at` (hypertable, 1-day chunks).

### `dora_snapshots` (hypertable)

Periodic snapshots of the four DORA metrics for trend analysis.

| Column                | Type          | Constraints            | Description             |
| --------------------- | ------------- | ---------------------- | ----------------------- |
| id                    | BIGSERIAL     | PRIMARY KEY            | Auto-incrementing ID    |
| team_id               | VARCHAR(64)   | NOT NULL               | Team identifier         |
| deployment_frequency  | NUMERIC(10,4) | NOT NULL               | Deployments per week    |
| lead_time_hours       | NUMERIC(10,2) | NULL                   | Lead time in hours      |
| change_failure_rate   | NUMERIC(5,4)  | NULL                   | 0.0000–1.0000           |
| time_to_restore_hours | NUMERIC(10,2) | NULL                   | MTTR in hours           |
| snapshot_window_start | TIMESTAMPTZ   | NOT NULL               | Window start            |
| snapshot_window_end   | TIMESTAMPTZ   | NOT NULL               | Window end              |
| recorded_at           | TIMESTAMPTZ   | NOT NULL DEFAULT NOW() | When snapshot was taken |

Partitioned by: `recorded_at` (hypertable, 7-day chunks).
Index: `(team_id, recorded_at DESC)` for per-team trend queries.

### `archetype_history`

Team archetype classification records — tracks how teams are categorized over time.

| Column      | Type         | Constraints                   | Description                                 |
| ----------- | ------------ | ----------------------------- | ------------------------------------------- |
| id          | BIGSERIAL    | PRIMARY KEY                   | Auto-incrementing ID                        |
| team_id     | VARCHAR(64)  | NOT NULL                      | Team identifier                             |
| archetype   | VARCHAR(32)  | NOT NULL                      | 'elite', 'high', 'medium', 'low', 'unknown' |
| snapshot_id | BIGINT       | REFERENCES dora_snapshots(id) | Source snapshot                             |
| confidence  | NUMERIC(3,2) | NULL                          | Classification confidence                   |
| recorded_at | TIMESTAMPTZ  | NOT NULL DEFAULT NOW()        | When classified                             |

Index: `(team_id, recorded_at DESC)` for archetype history queries.

### `wellbeing_surveys`

Developer wellbeing survey responses — used to correlate DORA metrics with team wellbeing.

| Column         | Type         | Constraints            | Description                     |
| -------------- | ------------ | ---------------------- | ------------------------------- |
| id             | BIGSERIAL    | PRIMARY KEY            | Auto-incrementing ID            |
| respondent_id  | VARCHAR(128) | NOT NULL               | Anonymous respondent identifier |
| survey_version | VARCHAR(16)  | NOT NULL               | Survey version tag              |
| q1_score       | SMALLINT     | CHECK (1-5)            | Wellbeing question 1            |
| q2_score       | SMALLINT     | CHECK (1-5)            | Wellbeing question 2            |
| q3_score       | SMALLINT     | CHECK (1-5)            | Wellbeing question 3            |
| q4_score       | SMALLINT     | CHECK (1-5)            | Wellbeing question 4            |
| q5_score       | SMALLINT     | CHECK (1-5)            | Wellbeing question 5            |
| free_text      | TEXT         | NULL                   | Optional qualitative feedback   |
| submitted_at   | TIMESTAMPTZ  | NOT NULL DEFAULT NOW() | When submitted                  |

Index: `(survey_version, submitted_at)` for survey analysis.

### `vsi_stage_breakdown` (hypertable)

Value stream stage timing data — breakdown of lead time into individual stages.

| Column           | Type         | Constraints            | Description                                         |
| ---------------- | ------------ | ---------------------- | --------------------------------------------------- |
| id               | BIGSERIAL    | PRIMARY KEY            | Auto-incrementing ID                                |
| deployment_id    | VARCHAR(128) | NOT NULL               | Associated deployment                               |
| stage_name       | VARCHAR(64)  | NOT NULL               | e.g., 'commit', 'review', 'build', 'test', 'deploy' |
| duration_seconds | INTEGER      | NOT NULL               | Time spent in this stage                            |
| status           | VARCHAR(32)  | NOT NULL               | 'success', 'failure', 'skipped'                     |
| metadata         | JSONB        | NULL                   | Stage-specific context                              |
| recorded_at      | TIMESTAMPTZ  | NOT NULL DEFAULT NOW() | When stage completed                                |

Partitioned by: `recorded_at` (hypertable, 1-day chunks).
Index: `(deployment_id, stage_name)` for deployment breakdown queries.

## Interfaces

### SQL API — Init Scripts

<<<<<<< HEAD
The init scripts expose no network interfaces. They are consumed by:

- **psql** during container initialization (`docker-entrypoint-initdb.d/`)
- **testcontainers** in unit tests
- **bind-mount** in the fawkes resource plane

### SQL API — Application Access

The `dora_app` role has access to:

- `INSERT INTO event_queue (...) VALUES (...)` — enqueue events
- `SELECT/INSERT INTO raw_events` — read/write processed events
- `INSERT INTO dora_snapshots` — write metric snapshots
- `SELECT on archetype_history`, `wellbeing_surveys`, `vsi_stage_breakdown` — read-only

## Tradeoffs

| Decision              | Chosen                              | Rejected              | Rationale                                                                                        |
| --------------------- | ----------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------ |
| Base image            | `timescale/timescaledb:latest-pg16` | `postgres:16-alpine`  | TimescaleDB provides `time_bucket()`, `percentile_agg()`, and hypertables without index overhead |
| Partition key         | `recorded_at` timestamptz           | `id` or `team_id`     | Time-based partitioning is the natural access pattern for DORA metrics                           |
| Chunk interval        | 1 day (7 days for snapshots)        | 1 hour, 1 week        | 1-day chunks balance query performance with chunk management overhead                            |
| Migration style       | Forward-only SQL                    | ORM-based, framework  | Simple, portable, no runtime dependency                                                          |
| Credential management | psql inline SQL                     | Environment variables | Least-privilege, no credential leak risk, auditable                                              |
| Test framework        | testcontainers                      | mock/patch            | Tests the actual SQL against a real Postgres, not mocked behavior                                |

## Risks

| Risk                                     | Severity | Mitigation                                                                                                    |
| ---------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------- |
| TimescaleDB licensing changes            | LOW      | Schema uses standard PostgreSQL types + TimescaleDB hypertables only; could migrate to PG partition if needed |
| Schema drift between init and migrations | MEDIUM   | Migration 001 is generated from init scripts; diff check in CI                                                |
| Bind-mount path mismatch                 | LOW      | `docker-compose.dev.yml` uses relative path consistent with fawkes resource plane                             |
| Testcontainers port conflicts            | LOW      | Testcontainers uses random port mapping                                                                       |

## Governance Alignment

| Requirement | Design Decision                                                       | Status  |
| ----------- | --------------------------------------------------------------------- | ------- |
| Security    | Least-privilege `dora_app` role, no superuser, no env var credentials | COVERED |
| Idempotency | All scripts use `IF NOT EXISTS` / exception-safe patterns             | COVERED |
| Portability | All paths relative, bind-mount compatible                             | COVERED |
| Testability | Full schema tested via testcontainers with real Postgres              | COVERED |
| CI          | pytest runs on all pushes                                             | COVERED |
=======
| Decision                             | Rationale                                                                          | Alternatives Considered                                                          |
| ------------------------------------ | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| POSIX sh (not bash)                  | Maximum portability across containers, CI runners, and developer machines          | Bash — rejected because many minimal CI images lack bash                         |
| Interactive prompts in scripts       | Makes the script usable without reference docs; useful in incident stress          | Flags-only — rejected because reading docs under pressure is failure-prone       |
| curl with `\|\| true` in CI snippets | Prevents a DORA event collector from failing the pipeline                          | Hard fail — rejected; the pipeline should not fail because observability is down |
| Woodpecker `from_secret`             | Follows Woodpecker's security best practices                                       | Environment variables in pipeline config — less secure                           |
| Scripts exit code 1 on failure       | Manual scripts need the user to know it failed (unlike CI where it's non-critical) | Silent failure — dangerous; user would think FDRT is being tracked when it's not |
>>>>>>> d3be1bb (feat(collectors): add Woodpecker snippet, curl examples, manual incident scripts)
