# Decision 003 — Pipeline Trigger Map (current state)

**Date:** 2026-06-25
**Context:** Ground-truth audit of all 18 workflow files in `.github/workflows/`. Establishes which files trigger on which events, how jobs depend on each other, and where overlaps exist — before any restructuring begins.

---

## 1. Trigger Map

| # | File | Trigger Events | Jobs Defined | Calls / U uses |
|---|------|---------------|--------------|----------------|
| 1 | `pipeline.yml` | `pull_request [main]`, `push [main]`, `workflow_dispatch` | `pre-commit`, `post-commit`, `pre-deployment`, `deploy`, `post-deployment`, `pipeline-complete` | → `pre-commit.yml`, `post-commit.yml`, `pre-deployment.yml`, `deploy.yml`, `post-deployment.yml` |
| 2 | `ci.yml` | `pull_request [main]`, `push [main]`, `workflow_dispatch` | `validate` (pre-commit hooks only) | — (inline only) |
| 3 | `compute-metrics.yml` | `schedule (0 6 \* \* \*)`, `workflow_dispatch` | `compute-metrics` | — (inline only) |
| 4 | `pre-commit.yml` | `workflow_call`, `workflow_dispatch` | `preflight`, `docs-lint`, `lint`, `unit-tests`, `security`, `pre-commit-summary` | → `reusable-preflight.yml`, `docs-lint.yml`, `reusable-lint.yml`, `reusable-security-scanning.yml` |
| 5 | `post-commit.yml` | `workflow_call`, `workflow_dispatch` | `build-validate`, `post-commit-summary` | → `reusable-build.yml` |
| 6 | `pre-deployment.yml` | `workflow_call`, `workflow_dispatch` | `full-tests`, `security`, `dependency-review`, `pre-deployment-summary` | → `ci-tests.yml`, `reusable-security-scanning.yml`, `reusable-dependency-review.yml` |
| 7 | `deploy.yml` | `workflow_call` | `deploy` (inline) | — (inline steps) |
| 8 | `post-deployment.yml` | `workflow_call` | `health-check`, `smoke-tests`, `prometheus-verify`, `dora-metric`, `post-deployment-summary` | — (inline steps) |
| 9 | `reusable-preflight.yml` | `workflow_call` | `preflight` (inline) | — (inline steps) |
| 10 | `reusable-lint.yml` | `workflow_call` | `detect-changes`, `python-lint`, `shell-lint`, `yaml-lint`, `typescript-lint`, `go-lint`, `lint-summary` | — (inline steps) |
| 11 | `reusable-build.yml` | `workflow_call` | `build-validate` (inline) | — (inline steps) |
| 12 | `reusable-security-scanning.yml` | `workflow_call` | `security-scan` (inline) | — (inline steps) |
| 13 | `reusable-dependency-review.yml` | `workflow_call` | `dependency-review` (inline) | — (inline steps) |
| 14 | `reusable-tests.yml` | `workflow_call` | `unit-tests`, `compose-smoke`, `integration-tests`, `golden-path`, `test-summary` | — (inline steps) |
| 15 | `reusable-deploy.yml` | `workflow_call` | `deploy` (inline) | — (inline steps, NOT currently called by any orchestrator) |
| 16 | `reusable-post-deploy.yml` | `workflow_call` | `post-deploy-verify` (inline) | — (inline steps, NOT currently called by any orchestrator) |
| 17 | `ci-tests.yml` | `workflow_call` | `unit-tests`, `integration-tests`, `smoke-tests`, `e2e-tests`, `test-summary` | — (inline steps) |
| 18 | `docs-lint.yml` | `workflow_call` | `required-files`, `markdown-lint`, `link-check` | — (inline steps) |

---

## 2. Job Dependency Graph

### Orchestrator (pipeline.yml)

```
pipeline.yml (PR/push/workflow_dispatch)
│
├── pre-commit.yml  ─── parallel ─── preflight, docs-lint, lint, unit-tests, security
│                                      │
│                                      └── pre-commit-summary (needs: all above)
│
├── post-commit.yml ─── sequential ─── build-validate → post-commit-summary
│
├── pre-deployment.yml ─── parallel ─── full-tests, security, dependency-review
│                                         │
│                                         └── pre-deployment-summary (needs: all above)
│
├── deploy.yml ─── sequential (only if workflow_dispatch + inputs.run-deploy)
│   └── deploy (inline steps)
│
├── post-deployment.yml ─── needs: [deploy] (only if deploy ran)
│   │
│   ├── health-check (standalone)
│   ├── smoke-tests (needs: health-check)
│   ├── prometheus-verify (standalone)
│   └── dora-metric (standalone)
│       │
│       └── post-deployment-summary (needs: all above)
│
└── pipeline-complete (needs: all 5 phases)
```

### ci-tests.yml (called by pre-deployment.yml)

```
ci-tests.yml
│
├── unit-tests (if inputs.run-unit)
├── integration-tests
├── smoke-tests (needs: integration-tests)
├── e2e-tests (needs: smoke-tests)
│
└── test-summary (needs: all above)
```

### reusable-lint.yml (called by pre-commit.yml)

```
detect-changes
│
├── python-lint (needs: detect-changes, conditional on python detected)
├── shell-lint (needs: detect-changes, conditional on shell detected)
├── yaml-lint (needs: detect-changes, conditional on yaml detected)
├── typescript-lint (needs: detect-changes, conditional on ts detected)
├── go-lint (needs: detect-changes, conditional on go detected)
│
└── lint-summary (needs: detect-changes + all lint jobs)
```

### reusable-tests.yml (NOT currently called by any orchestrator)

```
unit-tests, compose-smoke (parallel)
│
├── integration-tests (needs: compose-smoke)
├── golden-path (needs: compose-smoke)
│
└── test-summary (needs: all above)
```

---

## 3. Call Chain Summary

```
pipeline.yml
  ├── pre-commit.yml
  │     ├── reusable-preflight.yml
  │     ├── docs-lint.yml
  │     ├── reusable-lint.yml
  │     │     └── (detect-changes → per-language lint jobs → lint-summary)
  │     ├── inline unit tests
  │     └── reusable-security-scanning.yml (scan-type: secrets)
  │
  ├── post-commit.yml
  │     └── reusable-build.yml
  │
  ├── pre-deployment.yml
  │     ├── ci-tests.yml (unit → integration → smoke → E2E)
  │     ├── reusable-security-scanning.yml (scan-type: all)
  │     └── reusable-dependency-review.yml
  │
  ├── deploy.yml (gated: workflow_dispatch + run-deploy)
  │
  └── post-deployment.yml (gated: deploy success)
```

---

## 4. Overlap & Anomaly Flags

### 🔴 Overlapping Trigger: `ci.yml` runs alongside `pipeline.yml`

Both `ci.yml` and `pipeline.yml` trigger on `pull_request [main]` and `push [main]`. They run in parallel, duplicating pre-commit hook execution. `ci.yml` is a legacy remnant that was never removed when `pipeline.yml` was created.

**Recommendation:** Remove `ci.yml` — its single job (`pre-commit run --all-files`) is already performed by `reusable-preflight.yml` within `pre-commit.yml` (Phase 1).

### 🟡 Phase workflows with dual triggers

`pre-commit.yml`, `post-commit.yml`, and `pre-deployment.yml` each have both `workflow_call` and `workflow_dispatch`. The `workflow_dispatch` allows standalone execution for debugging but is not wired into any automatic trigger — they can only be triggered manually or via `pipeline.yml`.

### 🟡 Orphaned reusable workflows

`reusable-deploy.yml` and `reusable-post-deploy.yml` exist but are **not currently called by any orchestrator**. `deploy.yml` and `post-deployment.yml` implement similar logic inline. These duplicate workflows represent technical debt.

**Recommendation:** Either consolidate into the inline versions or switch `pipeline.yml` to call the reusable versions.

### 🟡 Orphaned reusable-tests.yml

`reusable-tests.yml` exists but is **not currently called by any orchestrator**. The test pipeline uses `ci-tests.yml` instead (wired into `pre-deployment.yml`). `reusable-tests.yml` uses a different test structure (compose-smoke + golden-path) vs `ci-tests.yml` (integration → smoke → E2E).

**Recommendation:** Either consolidate the two test approaches or remove the unused workflow.

### 🟢 `compute-metrics.yml` is standalone

This is a scheduled cron job for DORA metric computation. It has no overlap with other workflows and operates independently.

---

## 5. Which file is the primary PR gate?

**`pipeline.yml`** — It orchestrates the full 5-phase lifecycle. Phases 1-3 (pre-commit, post-commit, pre-deployment) run on every PR and push to main and must pass before a PR is mergeable. Phases 4-5 (deploy, post-deployment) only run on manual `workflow_dispatch` with `inputs.run-deploy: true`.

## 6. Which file deploys?

**`deploy.yml`** — Called by `pipeline.yml` Phase 4, gated behind `workflow_dispatch + inputs.run-deploy`. Handles GitOps CD promotion: updates image tags in kustomization manifests, commits, pushes, waits for reconciliation, and supports rollback.

A secondary deploy workflow exists (`reusable-deploy.yml`) but is not currently wired into any orchestrator.

---

## Appendix: Quick Reference

```
Trigger types:          push [main], pull_request [main], workflow_dispatch, schedule, workflow_call
Standalone triggers:    pipeline.yml, ci.yml, compute-metrics.yml
workflow_call only:     15 files (all reusable* and phase workflows)
workflow_dispatch also: pipeline.yml, ci.yml, pre-commit.yml, post-commit.yml, pre-deployment.yml, compute-metrics.yml
Schedule only:          compute-metrics.yml
Solely workflow_call:   12 files (all reusable, deploy, post-deployment, ci-tests, docs-lint)
```
