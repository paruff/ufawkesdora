---
date: 2026-06-23
persona: platform-engineer
jtbd: "When I configure the uFawkesDORA pipeline, I want to implement a comprehensive 5-stage GitOps-aligned engineering lifecycle (Pre-Commit, Post-Commit, Pre-Deploy, Deploy, Post-Deploy) in this repo, so I can guarantee high-quality releases, zero regressions, and complete confidence with robust automated gates before any code hits production."
riskiest_assumption: "We assume that running full local docker-compose stacks (including TimescaleDB, the FastAPI ingestion engine, worker threads, and Playwright browsers) inside standard GitHub Actions runners is resource-performant, does not hit rate/resource limits, and can run deterministically without flake."
acceptance_criterion: "Given a PR is opened in the uFawkesDORA repo, when the CI Pipeline runs, then all 5 stages (Pre-Commit, Post-Commit, Pre-Deployment Validation, Deployment, Post-Deployment Verification) execute successfully, producing test, security, and quality gate reports, and gating the PR until all stages pass."
dora_ai_capability: "Cap7: Quality internal platforms"
dora_core_capability: "Continuous Integration & Deployment Automation"
metric: "change_failure_rate_pct"
measurement_source: "uFawkesDORA computed metrics"
baseline: "1.2% (2026-06-01)"
prior_art: "uFawkesPipe defines lightweight CI/CD with Woodpecker + Portainer. Existing reusable workflows in this repo define basic lint/security/test stages, but lack full 5-stage alignment with smoke/integration/E2E test stacks."
status: ready-for-spec
---

# Discovery Brief: 5-Stage GitOps-Aligned Engineering Lifecycle Pipeline

## Job to Be Done

"When I configure the uFawkesDORA pipeline, I want to implement a comprehensive 5-stage GitOps-aligned engineering lifecycle (Pre-Commit, Post-Commit, Pre-Deploy, Deploy, Post-Deploy) in this repo, so I can guarantee high-quality releases, zero regressions, and complete confidence with robust automated gates before any code hits production."

## Riskiest Assumption

**We assume that running full local docker-compose stacks (including TimescaleDB, the FastAPI ingestion engine, worker threads, and Playwright browsers) inside standard GitHub Actions runners is resource-performant, does not hit rate/resource limits, and can run deterministically without flake.**

_Mitigation:_

1. Use distinct, isolated Docker Compose configurations (`docker-compose.integration.yml` and `docker-compose.test.yml`) with minimal, tailored service profiles.
2. Ensure database-ready checks (`pg_isready` / `healthy` container states) are explicitly coded so tests never run against uninitialized services.
3. Clean up Docker volumes, networks, and containers aggressively between test jobs using `docker compose down -v`.

## Acceptance Criterion

> **Given** a PR is opened in the uFawkesDORA repo,
> **when** the CI Pipeline runs,
> **then** all 5 stages (Pre-Commit, Post-Commit, Pre-Deployment Validation, Deployment, Post-Deployment Verification) execute successfully:
>
> - Pre-Commit: Linting, formatting, type-checking, and secret scanning pass.
> - Post-Commit: App builds successfully, fast unit tests execute and pass, security SAST/SCA and license compliance verify.
> - Pre-Deployment Validation: An isolated integration stack starts up, runs database schema tests against real TimescaleDB, executes smoke tests verifying `/health` endpoints via curl, and runs E2E tests verifying the full ingestion-to-metric flow.
> - Deployment & Post-Deployment: Simulates progressive/CD promotion and verifies rollback safety.

## DORA Outcome Target

- **Capability:** Cap7: Quality internal platforms
- **Metric:** change_failure_rate_pct
- **Current baseline:** 1.2%
- **Target:** 0.0% (Zero regressions reaching main)
- **Measurement:** uFawkesDORA metrics computation

## Prior Art

- **Existing Workflows:** We have `reusable-preflight.yml`, `reusable-lint.yml`, `reusable-security-scanning.yml`, `reusable-dependency-review.yml`, `reusable-build.yml`, and `ci-tests.yml` in `.github/workflows/`.
- **Missing Elements:** The existing `ci-tests.yml` splits unit and integration tests, but lacks a complete pre-deployment validation layout with smoke tests and E2E playbooks, as well as post-deployment verification. There is no automated curl smoke check on the full compose stack, nor any Playwright E2E automation in place.
- **Docker Compose:** We only have `docker-compose.dev.yml` for local development. There is no separate `docker-compose.integration.yml` or `docker-compose.test.yml` as described by the user's templates.

## Notes

This discovery brief lays out the specification and design for a state-of-the-art GitOps-aligned CI/CD pipeline that maps directly to the five key lifecycle stages. The implementation will define the necessary Compose files, E2E playbooks, and update the CI workflows.
