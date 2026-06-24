# Design: 5-Stage GitOps-Aligned Engineering Lifecycle Pipeline

## 1. Architectural Philosophy: The Two-Tier Reusability Model

To satisfy the requirement that this pipeline supports not just `uFawkesDORA` but many other repositories in the `uFawkes` platform suite and beyond, the design is split into two distinct tiers:

1. **The Platform Tier (Reusable Workflows)**:

   - Stateless, generic workflow templates (e.g., `reusable-preflight.yml`, `reusable-lint.yml`, `reusable-security-scanning.yml`, `reusable-dependency-review.yml`, `reusable-build.yml`, and `reusable-tests.yml`).
   - Standardized inputs and outputs that accept common configuration parameters (e.g., node-version, python-version, folders to scan).
   - Designed to be maintained once and inherited by all repositories in the suite via GitHub Actions `uses:` statements.

2. **The Repository Tier (Local Concrete Implementation)**:
   - Local orchestrators (e.g. `ci-pipeline.yml`) that tie the reusable workflows together in a repository-specific DAG (Directed Acyclic Graph).
   - Repository-specific testing configurations, such as `docker-compose.integration.yml` and `docker-compose.test.yml`, which map the local application architecture.
   - Fast, local unit tests under `tests/unit` and local integration/E2E playbooks under `tests/integration`.

---

## 2. The 5-Stage Pipeline DAG

The concrete pipeline is structured as an automated, progressive sequence of gates to ensure that failures are caught early (low cost) before triggering intensive test stacks or deployments (high cost).

```
[PR/Push Trigger]
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 1: PRE-COMMIT / PRE-FLIGHT                       │
│ - reusable-preflight.yml (Conventional Commits, GHA)   │
│ - local pre-commit hooks (Ruff, Black, Gitleaks, etc.) │
└──────────────────────┬─────────────────────────────────┘
                       │ (Pass)
                       ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 2: POST-COMMIT CI (BUILD & STATIC SCANS)         │
│ - ruff/eslint/golangci-lint (reusable-lint.yml)        │
│ - trivy/safety/gitleaks (reusable-security-scanning.yml)│
│ - dependency-review (reusable-dependency-review.yml)   │
└──────────────────────┬─────────────────────────────────┘
                       │ (Pass)
                       ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 3: BUILD & COMPILATION                           │
│ - Docker multi-stage build (reusable-build.yml)        │
│ - `:latest` tag check                                  │
└──────────────────────┬─────────────────────────────────┘
                       │ (Pass)
                       ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 4: PRE-DEPLOYMENT VALIDATION (ISOLATED STACKS)    │
│ - Fast unit tests (no Docker)                          │
│ - Start integration stack (docker-compose.integration) │
│ - Real database schema tests (test_schema.py)          │
│ - Curl smoke test retry loop against `/health`         │
│ - E2E tests (verify ingestion-to-snapshot flow)        │
└──────────────────────┬─────────────────────────────────┘
                       │ (Pass)
                       ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 5: DEPLOYMENT & POST-DEPLOYMENT VERIFICATION     │
│ - GitOps promotion & state reconciliation              │
│ - Post-deploy health verification                      │
│ - Rollback trigger on failed smoke verification        │
└────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Stage Design

### 3.1 Stage 1: Pre-Commit (Local & PR Gate)

- **Local**: Developers use local `pre-commit` hooks. If any hook fails (formatting, trailing whitespace, secrets), the commit is aborted.
- **CI**: `reusable-preflight.yml` checks that:
  - Commit messages follow Conventional Commits.
  - `.env.example` has no concrete secrets (only allows placeholders or `${VAR}` templates).
  - No secrets are leaked via Gitleaks.

### 3.2 Stage 2: Post-Commit CI

- **Linting**: Auto-detects languages (Python, Go, JS/TS, Shell, YAML) and runs language-appropriate lints in parallel.
- **Security Scans**:
  - Trivy scans the filesystem for vulnerabilities.
  - Safety (Python) or NPM Audit (JS/TS) checks third-party dependencies.
  - Dependency Review acts as a pull-request gate to prevent vulnerable packages from being merged.

### 3.3 Stage 3: Build & Validate

- **Docker Building**: Executes multi-stage container builds.
- **Supply Chain Protection**: Validates the `compose.yaml` and `docker-compose.dev.yml` to ensure no container uses `:latest` tags, guaranteeing deterministic builds.

### 3.4 Stage 4: Pre-Deployment Validation (Isolated Test Stack)

This is the core test execution stage. To achieve high fidelity without external environment dependency, the stage runs in three parts:

#### Part A: Integration Testing (`docker-compose.integration.yml`)

- Starts a TimescaleDB instance and the FastAPI ingestion API.
- Runs `pytest tests/integration/test_schema.py` which verifies:
  - Database schema initializes correctly.
  - All tables and indexes exist.
  - Hypertable conversions succeed.
  - Least-privilege grants on `event_queue`, `raw_events`, and `dora_snapshots` are respected.

#### Part B: Smoke Testing (Health Check Loop)

- Starts the full stack.
- Performs an automated curl smoke-check from an ephemeral container using:
  ```sh
  docker run --network host appropriate/curl \
    -s --retry 10 --retry-delay 2 --retry-connrefused http://localhost:8088/health
  ```
- This guarantees that the API is fully initialized and communicating with the database pool before proceeding.

#### Part C: E2E System Flow Verification

- A simulated event producer posts canonical events (e.g. `deployment` and `incident`) to the ingestion API.
- The worker processes them into `raw_events`.
- The compute cron runs `compute/metrics.py` to calculate DORA metrics.
- The test asserts that the resulting database snapshot contains accurate computed values.

### 3.5 Stage 5: Deployment & Verification

- Uses GitOps patterns where merging to `main` promotes the image tag.
- If a post-deployment health check fails or a Prometheus critical alert trips (e.g. `DoraFDRTSpike` or a system level crash), an automated CD trigger executes a rollback to the previous stable release tag.

---

## 4. Key Design Tradeoffs

### Tradeoff 1: Docker-backed Integration Tests in CI vs. Stubbing / Mocking

- **Option A (Stubbing)**: Mock all database and external queries in unit tests. Highly fast but low fidelity — schema syntax, hypertable conversions, and database grant constraints are completely untested in the pipeline.
- **Option B (Docker Stacks)**: Spin up real TimescaleDB containers using testcontainers or local docker-compose. Slower but catches syntax errors, schema migration failures, and permission errors before deployment.
- **Decision**: **Option B (Docker Stacks)**. This satisfies our goal of high confidence. We mitigate the speed penalty by keeping unit tests fast and containerless, running the Docker-backed integration and smoke tests in a separate, isolated job in the PR pipeline.

### Tradeoff 2: Inline Curl Smoke Loop vs. Playwright/Acceptance Framework

- **Option A (Curl-only)**: A lightweight, portable shell script checking `/health` via curl. Extremely fast, robust, and zero install overhead.
- **Option B (Playwright)**: Full node browser automation tool. Excellent for UIs, but since uFawkesDORA is a stateless backend plane with no frontend UI of its own, Playwright is a heavy, unnecessary dependency.
- **Decision**: **Option A (Curl-only)**. We will use a curl smoke test loop to verify API and database connectivity, and use python-based request validation for API-to-database E2E testing, keeping the pipeline lean and avoiding Playwright bloat in backend-only repos.

---

## 5. Reusability Plan for other uFawkes repos

To inherit this design, other repositories in the suite (e.g., `uFawkesObs`, `uFawkesSec`, `uFawkesAI`) only need to:

1. Reference the centralized reusable workflows in `.github/workflows/`.
2. Define their local `docker-compose.integration.yml` file mapping their local runtime stack.
3. Configure their local `ci-pipeline.yml` DAG to match their test gates.
   This ensures a unified, golden-path CI/CD experience across the entire organization.
