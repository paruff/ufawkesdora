# Specification: Resource Plane Postgres Schema with TimescaleDB

## User Story

As a DORA metrics platform engineer, I want a PostgreSQL + TimescaleDB schema for all uFawkesDORA data so that the platform can store, query, and analyze time-series deployment metrics, wellbeing surveys, and VSM stage data with efficient time-bucketed aggregations.

## Functional Requirements

### REQ-001: Database Initialization

Create three databases (`dora_metrics`, `infisical`, `defectdojo`) via idempotent psql script with least-privilege roles. No environment variable injection for database credentials.

### REQ-002: DORA Metrics Schema

Define tables for all uFawkesDORA data domains:

- `event_queue` — incoming event buffer
- `raw_events` — processed event records with timestamps
- `dora_snapshots` — periodic DORA metric snapshots
- `archetype_history` — team archetype classification records
- `wellbeing_surveys` — developer wellbeing survey responses
- `vsi_stage_breakdown` — value stream stage timing data

### REQ-003: Application Role

Create a `dora_app` role with least-privilege grants: INSERT on event_queue, SELECT/INSERT on raw_events, INSERT on dora_snapshots. No superuser, no schema ownership.

### REQ-004: TimescaleDB Hypertables

Convert `raw_events`, `dora_snapshots`, and `vsi_stage_breakdown` to TimescaleDB hypertables partitioned by time for efficient time-bucket queries.

### REQ-005: Forward-Only Migrations

Provide a migration system starting with `001-initial-schema.sql` that matches the init scripts. First run equals migration 001.

### REQ-006: Development Environment

Provide a `docker-compose.dev.yml` with a local TimescaleDB container for standalone development without the full resource plane.

### REQ-007: Schema Validation Tests

Unit tests that spin up a test Postgres container via testcontainers, apply all init scripts, verify all tables exist, verify hypertable creation, and verify role permissions.

## Non-Functional Requirements

### NFR-001: Idempotency

All init scripts must be safe to re-run (idempotent). Running them multiple times must produce the same result.

### NFR-002: Security

- No hardcoded credentials in scripts
- Least-privilege role grants only
- No superuser roles for application access
- No environment variable injection for database credentials

### NFR-003: Compatibility

- Use `timescale/timescaledb:latest-pg16` as base image
- PostgreSQL 16 compatibility
- SQL standard compliant where possible

### NFR-004: Portability

Init scripts are bind-mounted into the resource plane container — no hardcoded paths.

## Constraints

- Schema lives in uFawkesDORA repo, database instance is in fawkes resource plane
- Using TimescaleDB not vanilla PostgreSQL
- Forward-only migrations (no rollbacks)
- Python 3.11+ for test suite
- testcontainers-postgres for test infrastructure

## Assumptions

- PostgreSQL + TimescaleDB will be run via Docker
- The `dora_metrics` database will be created on the resource plane Postgres instance
- bind mounts will provide the init scripts to the container

## Dependencies

- Docker and docker-compose for local development
- Python testcontainers library for tests
- timescaledb Docker image
- psql client for init scripts

## Out of Scope

- Resource plane Terraform/Pulumi configuration (in fawkes repo)
- Application-layer API for writing to these tables
- CI/CD pipeline for the init scripts
- Data retention policies and archival

## Acceptance Criteria

- [ ] AC-01: `database/init/00-create-databases.sh` creates `dora_metrics`, `infisical`, `defectdojo` databases with least-privilege roles via psql, not env vars. Script is idempotent (safe to re-run).
- [ ] AC-02: `database/init/01-dora-schema.sql` creates all tables: `event_queue`, `raw_events`, `dora_snapshots`, `archetype_history`, `wellbeing_surveys`, `vsi_stage_breakdown`
- [ ] AC-03: `database/init/02-dora-roles.sql` creates `dora_app` role with least-privilege grants (INSERT on event_queue, SELECT/INSERT on raw_events, INSERT on dora_snapshots). NO superuser, NO schema ownership.
- [ ] AC-04: `database/timescaledb/hypertables.sql` converts `raw_events`, `dora_snapshots`, `vsi_stage_breakdown` to TimescaleDB hypertables
- [ ] AC-05: `database/migrations/001-initial-schema.sql` forward-only migration matching the init scripts
- [ ] AC-06: `tests/unit/test_schema.py` spins up test Postgres container via testcontainers, applies all init scripts, verifies all tables exist, verifies hypertable creation, verifies role permissions are correct (not superuser)
- [ ] AC-07: `docker-compose.dev.yml` includes a local TimescaleDB container for solo development
- [ ] AC-08: All tests pass in CI

## Governance Alignment

| Requirement | Status  | Notes                                                   |
| ----------- | ------- | ------------------------------------------------------- |
| Security    | COVERED | Least-privilege roles, no superuser, no hardcoded creds |
| Pipeline    | COVERED | CI tests via pytest                                     |
| Idempotency | COVERED | Scripts safe to re-run                                  |
| Portability | COVERED | Bind-mount compatible, no hardcoded paths               |
