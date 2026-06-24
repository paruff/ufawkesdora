# Specification: 5-Stage GitOps-Aligned Engineering Lifecycle Pipeline

## 1. Introduction & Context

This specification outlines the requirements for establishing a comprehensive, industry-standard 5-stage CI/CD and GitOps pipeline for the uFawkesDORA repository.

To achieve maximum confidence with minimum waste, the pipeline enforces progressive validation gates where fast-running static checks execute first, followed by isolated unit tests, container builds, and finally multi-container integration, smoke, and end-to-end (E2E) testing.

The 5 stages are:

1. **Pre-Commit Stage**: Linting, formatting, type checks, secret scanning, and local unit test availability.
2. **Post-Commit CI Stage**: Docker multi-stage container builds, fast unit testing, static application security testing (SAST), software composition analysis (SCA), and dependency reviews.
3. **Pre-Deployment Validation**: Smoke tests against running container stacks, integration tests against real TimescaleDB instances, and E2E system flow verification.
4. **Deployment (GitOps CD)**: Promotion mechanisms, cluster state synchronization, progressive delivery hooks, and policy-as-code validations.
5. **Post-Deployment Verification**: Dynamic validation, production smoke tests, telemetry and alert check, and automated rollback triggers.

---

## 2. Functional Requirements

### 2.1 Stage 1: Pre-Commit (Pre-Flight Gates)

- **REQ-1.1**: The repository must enforce pre-commit hooks locally and in CI to perform code quality scans.
- **REQ-1.2**: All Python files must be linted via `ruff` and formatted via `black`/`prettier`.
- **REQ-1.3**: All Shell scripts must be validated via `shellcheck` and formatted via `shfmt`.
- **REQ-1.4**: All JSON/YAML files must pass syntax validation.
- **REQ-1.5**: Secret scanning via `Gitleaks` and `detect-secrets` must run on every change to prevent accidental commit of API keys or database passwords.

### 2.2 Stage 2: Post-Commit CI

- **REQ-2.1**: A multi-stage, non-root Docker build of the ingestion API and compute worker must succeed.
- **REQ-2.2**: Fast unit tests (running in <10 seconds and requiring no Docker container dependencies) must execute and pass on every commit.
- **REQ-2.3**: Vulnerability and dependency license scanning must execute on the codebase and the generated container layers.
- **REQ-2.4**: Quality gates must enforce code coverage thresholds of at least 80% on all core compute and API logic.

### 2.3 Stage 3: Pre-Deployment Validation (Staging/Ephemeral Stack)

- **REQ-3.1 (Integration Testing)**: The CI runner must spin up an isolated integration stack (`docker-compose.integration.yml`) with:
  - A real TimescaleDB container
  - An ingestion API container
  - An async processor worker container
- **REQ-3.2**: Integration tests must execute against this live stack to verify that PostgreSQL tables, hypertables, and least-privilege grants initialize correctly, and that the async worker successfully dequeues and validates events.
- **REQ-3.3 (Smoke Testing)**: A full compose stack must start, and a curl-based smoke test must poll the `/health` endpoint of the ingestion API up to 10 times with backoff until a successful 200 OK is returned.
- **REQ-3.4 (End-to-End Testing)**: The pipeline must execute an end-to-end suite simulating a full user journey:
  - Enqueue a deployment success event and an incident event.
  - Trigger the `compute/metrics.py` job to calculate the DORA metrics.
  - Verify that the resulting snapshot in `dora_snapshots` correctly reflects the computed FDRT (Failure Deployment Recovery Time) and Change Failure Rate (CFR).
- **REQ-3.5 (Log Dumping)**: On any integration, smoke, or E2E failure, the pipeline must dump the container logs to `integration.log` and save them as workflow artifacts for rapid troubleshooting.

### 2.4 Stage 4: Deployment (GitOps CD)

- **REQ-4.1 (Reconciliation & Promotion)**: The system must define clear promotional boundaries where code is merged to `main` before triggering environment updates.
- **REQ-4.2 (Policy Gates)**: Policy checks must ensure that Kubernetes manifests or compose configurations do not contain security risks (e.g. running as root, missing resource limits, or using `:latest` tags).

### 2.5 Stage 5: Post-Deployment Verification

- **REQ-5.1 (Active Monitoring)**: The system must verify that telemetry flows and Prometheus alert rules are active after deployment.
- **REQ-5.2 (Rollback Automation)**: The system must document and simulate rollback triggers where a failed smoke check or alert triggers an automated GitOps revert.

---

## 3. Non-Functional Requirements

### 3.1 NFR-001: Isolation

Each test tier (Integration, Smoke, E2E) must run in a completely isolated network and container space. Databases must be fresh with no shared state or persistent volumes leaking between runs.

### 3.2 NFR-002: Speed

- Pre-Commit / Pre-Flight stage must run in under 2 minutes in CI.
- Unit testing must complete in under 10 seconds.
- Smoke testing must confirm stack health in under 90 seconds.
- Entire Stage 1-4 pipeline execution must complete in under 8 minutes in a standard GitHub Actions runner.

### 3.3 NFR-003: Graceful Teardown

On completion (both success and failure), all running Docker containers, volumes, and networks created by the test stacks must be destroyed to prevent runner pollution.

---

## 4. Acceptance Criteria

| ID        | Given                              | When                                                            | Then                                                                                           |
| --------- | ---------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| **AC-01** | A developer makes a change locally | They attempt to commit or run pre-commit                        | `ruff`, `black`, `shellcheck`, and Gitleaks checks must run and pass before commit.            |
| **AC-02** | A pull request is submitted        | The CI pipeline starts                                          | `ci-pipeline.yml` executes `reusable-preflight.yml`, linting, and security scans sequentially. |
| **AC-03** | The build stage executes           | Container building is triggered                                 | Multi-stage Docker builds of `ingestion` succeed, and `:latest` checks pass.                   |
| **AC-04** | Fast unit tests are triggered      | `make test-unit` or `pytest tests/unit` runs                    | All 113+ unit tests execute successfully in <5 seconds without requiring Docker.               |
| **AC-05** | The integration stage starts       | `docker compose -f docker-compose.integration.yml up -d` is run | A fresh TimescaleDB + API + Worker stack boots and waits for health checks.                    |
| **AC-06** | Integration tests execute          | `pytest tests/integration` runs against the stack               | Database schema, table constraints, and role permissions are validated successfully.           |
| **AC-07** | Integration tests fail             | Any test in the integration job throws an error                 | Full container logs are written to `integration.log` and uploaded as GHA artifacts.            |
| **AC-08** | The smoke stage starts             | The smoke test job runs curl against the health endpoint        | The API returns `{"status":"ok"}` under 10 attempts with connection-refused retries.           |
| **AC-09** | The E2E stage starts               | A mock event sequence is posted and compute job is run          | A snapshot is generated in `dora_snapshots` matching the expected 2025 metric values.          |
| **AC-10** | A test stack completes             | The job finishes (success or failure)                           | `docker compose down -v` is executed, cleaning up all containers, networks, and volumes.       |
