# Design: uFawkesDORA Two-Plane Architecture

## 1. Architectural Philosophy: The Two-Plane Model

To satisfy the requirement that uFawkesDORA supports reliable, long-term storage of DORA event data while allowing the compute layer to be freely redeployed, the design follows a strict two-plane separation:

1. **The Compute Plane (Stateless)**:
   - Freely redeployable components: ingestion API, event processor, metric compute jobs
   - No persistent state storage - all state lives in the resource plane
   - Designed for horizontal scaling and frequent updates

2. **The Resource Plane (Stateful)**:
   - Persistent data storage: PostgreSQL with TimescaleDB extension
   - Contains all historical event data, computed metrics, and metadata
   - Independent lifecycle - survives compute plane redeployments
   - Shared with other uFawkes* services (uFawkesObs, Infisical, DefectDojo) via database-per-service pattern

This separation ensures that historical DORA data is preserved even when the compute layer is updated or recreated.

## 2. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  EVENT SOURCES                                                              │
│                                                                             │
│  GitHub ────────────────────────────(HTTP POST, canonical schema)───────┐  │
│  Woodpecker CI ──────────────────(HTTP POST, canonical schema)──────────┤  │
│  Portainer webhooks ─(HTTP POST, canonical schema)──────────────────────┤  │
│  Incident webhook ───(HTTP POST, canonical schema)──────────────────────┘  │
│  (Grafana OnCall / PagerDuty / manual curl)                               │
└─────────────────────────────────────────────────────────────────────────────┘
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

## 3. Detailed Component Design

### 3.1 Ingestion API (stateless)
- **Technology**: FastAPI
- **Endpoint**: `POST /event` for receiving canonical events
- **Responsibilities**:
  - Validate incoming events against JSON schemas
  - Enqueue valid events to PostgreSQL `event_queue` table using SKIP LOCKED pattern
  - Return appropriate HTTP status codes (201 for success, 422 for validation errors)
  - Health check endpoint (`GET /health`) reporting queue depth
- **Stateless**: No local storage; all state managed via resource plane PostgreSQL

### 3.2 Event Processor (stateless background worker)
- **Technology**: Python worker with asyncpg
- **Responsibilities**:
  - Dequeue events from `event_queue` using `SELECT FOR UPDATE SKIP LOCKED`
  - Persist events to `raw_events` table in PostgreSQL
  - Emit OpenTelemetry counters to uFawkesObs OTel Collector
  - Forward structured logs to uFawkesObs Loki
  - Handle retry logic (max 3 attempts before marking as failed)
- **Event Loss Prevention**: SKIP LOCKED pattern ensures no events lost during redeployments

### 3.3 Metric Compute Job (cron-based, stateless)
- **Technology**: Python script executed via cron (GitHub Actions scheduled workflow)
- **Responsibilities**:
  - Compute all five DORA metrics from `raw_events` using TimescaleDB SQL functions
  - Calculate Rework Rate and Value Stream Indicators
  - Write results to `dora_snapshots` table
  - Push metrics to uFawkesObs Prometheus pushgateway for alerting and Grafana visualization
  - Set `proxy_metrics` flag when fallback data sources are used
- **Key Computations**:
  - Deployment Frequency: Count of successful deployments per week
  - Lead Time: `deployed_at - first_commit_at` (falls back to PR open time if needed)
  - FDRT: Time between failed deployment and next successful deployment of same service (NOT incident resolution time)
  - Change Failure Rate: Percentage of deployments with status 'failed' or 'rollback'
  - Rework Rate: Percentage of deployments with associated user-visible rework events

### 3.4 Resource Plane (Stateful Storage)
- **Technology**: PostgreSQL 16 with TimescaleDB extension
- **Databases**:
  - `dora_metrics`: Contains all uFawkesDORA data
  - `infisical`: For secret management (shared service)
  - `defectdojo`: For security tracking (shared service)
- **Key Tables**:
  - `event_queue`: SKIP LOCKED queue for zero event loss
  - `raw_events`: Immutable event store (converted to hypertable)
  - `dora_snapshots`: Computed metrics (converted to hypertable)
  - `archetype_history`: Team classifications over time
  - `wellbeing_surveys`: Quarterly survey responses
  - `vsi_stage_breakdown`: Value stream stage timing data
- **Access Pattern**:
  - Compute plane reads/writes via SQL
  - Grafana reads via PostgreSQL datasource plugin (for snapshots, archetypes, etc.)
  - Prometheus scrapes metrics pushed by compute job (for time-series dashboards/alerts)

### 3.5 Communication Patterns
- **Event Ingestion**: HTTP POST to `/event` (JSON payload)
- **Internal Communication**: Database tables (event queue → raw events → snapshots)
- **Telemetry Output**:
  - OpenTelemetry counters → uFawkesObs OTel Collector → Tempo/Prometheus
  - Structured logs → uFawkesObs Loki
  - Prometheus metrics → uFawkesObs Prometheus (via pushgateway)
- **Alerting**: Prometheus Alertmanager → Notification channels (Slack, email, etc.) - **OUTBOUND ONLY**
- **Dashboard Data**:
  - Time-series panels: Prometheus (metrics pushed by compute job)
  - Current value/table panels: PostgreSQL (via Grafana datasource plugin)

## 4. Key Design Decisions

### Decision 1: PostgreSQL with TimescaleDB as Primary Store
- **Why**: Raw events require relational joins (rework→deployment via deployment_sha, PR→deployment via commit_sha) that Prometheus cannot express
- **TimescaleDB Benefits**:
  - Automatic partitioning via hypertables for time-series data
  - SQL-native time_bucket() and percentile_agg() functions for efficient aggregations
  - Full SQL expressiveness for complex queries and joins
- **Trade-off**: Slightly more complex operational model vs pure Prometheus, but necessary for correctness

### Decision 2: SKIP LOCKED Event Queue for Zero Event Loss
- **Why**: Stateless compute nodes lose events during redeployments without buffering
- **Implementation**:
  - `event_queue` table with status column (pending/processing/done/failed)
  - Workers claim work with `SELECT FOR UPDATE SKIP LOCKED LIMIT 1`
  - No external queueing infrastructure needed (uses existing PostgreSQL)
- **Throughput**: ~500 events/second - sufficient for platform scale (<100 deploys/day across all services)

### Decision 3: Strict Separation of Concerns in Alerting
- **Why**: Alertmanager is a notification router that must never feed data back into the system
- **Implementation**:
  - Incident events come from incident management sources (Grafana OnCall, PagerDuty, manual curl)
  - Alertmanager only sends notifications OUT to Slack, email, PagerDuty, etc.
  - No paths exist from Alertmanager back to the ingestion API
- **Benefit**: Prevents feedback loops and maintains clear data flow boundaries

### Decision 4: Multi-Database PostgreSQL via Init Scripts
- **Why**: `POSTGRES_MULTIPLE_DATABASES` is not a standard Postgres environment variable
- **Implementation**:
  - Init script in `/docker-entrypoint-initdb.d/` creates additional databases
  - Uses least-privilege roles per service with minimum necessary permissions
  - Idempotent design safe for re-runs
- **Benefit**: Proper isolation between services while sharing the same PostgreSQL instance

## 5. Data Flow Examples

### 5.1 Normal Deployment Event Flow
1. GitHub Action → POST `/event` {event_type: "deployment", status: "success"}
2. Ingestion API validates schema, enqueues to `event_queue`
3. Event Processor dequeues, writes to `raw_events`, pushes OTel counter, pushes Loki log
4. Metric Compute Job (cron) reads from `raw_events`, computes metrics
5. Writes to `dora_snapshots`, pushes Prometheus metrics to uFawkesObs pushgateway
6. Grafana displays:
   - Time-series panels: Prometheus (from pushgateway)
   - Current value panels: PostgreSQL (dora_snapshots table)
   - Tables: PostgreSQL (via datasource plugin)

### 5.2 Incident Event Flow (for FDRT Calculation)
1. PagerDuty/webhook → POST `/event` {event_type: "incident", status: "opened"}
2. Same ingestion/processing pipeline as above
3. Later: GitHub Action → POST `/event` {event_type: "deployment", status: "success"}
4. Metric Compute Job calculates FDRT as: `next_successful_deploy_time - failed_deploy_time`
   - **NOT** incident resolution time (that would be old MTTR definition)
   - This is the 2025 DORA reclassification: FDRT is a Throughput metric
5. Result stored in `dora_snapshots.fdrt_p50_hours`

### 5.3 Rework Event Flow (for Rework Rate Calculation)
1. Monitoring system/webhook → POST `/event` {event_type: "rework", user_visible: true}
2. Same ingestion/processing pipeline
3. Metric Compute Job calculates:
   `rework_rate = COUNT(rework WHERE user_visible=true) / COUNT(deployment WHERE status='success') * 100`
4. Result stored in `dora_snapshots.rework_rate_pct`

## 6. Security and Compliance Considerations

### 6.1 Data Protection
- All event data stored in PostgreSQL with standard database security
- Wellbeing survey data access restricted to `dora_app` role only
- No individual response data exposed in Grafana or dashboards
- Database credentials managed via Infisical (separate service in resource plane)

### 6.2 Network Security
- Compute plane and resource plane communicate over isolated Docker network (`fawkes-resource-net`)
- No direct external access to resource plane databases
- Ingestion API is the only externally exposed component (HTTPS terminated at ingress)

### 6.3 Audit and Traceability
- All events immutable once written to `raw_events` (append-only design)
- Complete lineage from event source to computed metric
- Structured logging to Loki enables forensic analysis
- OTel traces show end-to-end processing latency

## 7. Scalability and Performance Considerations

### 7.1 Horizontal Scaling
- Ingestion API: stateless, can run multiple instances behind load balancer
- Event Processor: multiple instances safe due to SKIP LOCKED queue locking
- Metric Compute Job: singleton by design (cron job), but could be sharded by repo
- Resource Plane: PostgreSQL vertical scaling (read replicas for heavy dashboard usage)

### 7.2 Performance Optimizations
- TimescaleDB hypertables automatically partition time-series data
- Indexes on `repo` and `occurred_at` for efficient tenant-scoped queries
- Materialized views could be added for expensive aggregations (future work)
- Connection pooling via `asyncpg` in all Python components

### 7.3 Resource Requirements
- Compute Plane: Minimal CPU/memory (mostly I/O wait on database/network)
- Resource Plane: Scales with event storage requirements (approx 1KB per event, 100 bytes per snapshot)
- For 1000 events/day: ~365MB/year raw events, negligible snapshot storage
- Wellbeing surveys: minimal storage (quarterly surveys, <1KB each)

## 8. Extensibility Points

### 8.1 Adding New Metric Types
- Extend `compute/metrics.py` with new SQL queries
- Add columns to `dora_snapshots` table
- Update Grafana dashboards with new panels
- Add Prometheus pushgateway metrics

### 8.2 New Event Sources
- Implement new collector (GitHub Action, webhook snippet, etc.)
- Validate against existing schemas in `events/` directory
- No changes needed to core ingestion or processing pipelines

### 8.3 New Dashboard Types
- Create new Grafana JSON in `dashboards/` directory
- Use existing datasources (Prometheus for time-series, Postgres for current values)
- Add to provisioning in uFawkesObs

### 8.4 Additional Notification Channels
- Extend `notifications/` directory with new delivery mechanisms
- Update Alertmanager routing or create new workflows
- Maintain separation between alerting (OUTBOUND only) and data flow

## 9. Relationship to Other uFawkes* Services

### 9.1 uFawkesObs (Observability Platform)
- Provides: Prometheus, Loki, Tempo, OTel Collector, Grafana
- Receives from uFawkesDORA: OTel counters, Loki logs, Prometheus metrics
- Provides to uFawkesDORA: Queryable metrics/logs for debugging and alerting
- Shared resource plane: PostgreSQL databases (different schemas/databases)

### 9.2 Infisical (Secret Management)
- Provides: Dynamic secrets, certificate management, encryption as a service
- Used by: All services for credential rotation and secure secret distribution
- Integrated via: Standard API calls from application code

### 9.3 DefectDojo (Security Program Management)
- Provides: Vulnerability management, compliance tracking, security testing
- Receives from uFawkesDORA: Security event data (if implemented)
- Shared resource plane: PostgreSQL database (separate schema)

This two-plane architecture provides a solid foundation for a reliable, scalable DORA metrics system that preserves data integrity while allowing rapid innovation in the compute layer.
