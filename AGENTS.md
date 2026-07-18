# AGENTS.md — uFawkesDORA Agent Guide

## Skill Suite

This repository is part of the uFawkesAI suite. Agents operating in this repo should load the following skills depending on the task:

| Task Type                 | Relevant Skills                                                     |
| ------------------------- | ------------------------------------------------------------------- |
| CI/CD Pipeline Fix        | `ci-fix-workflow`, `build`, `test-execution`                        |
| Schema / Data Model       | `spec`, `spec-k8s-policy`                                           |
| Documentation             | `documentation`, `ai-stance`                                        |
| Security / Compliance     | `sast`, `container-security`, `dependency-scanning`                 |
| Integration / E2E Testing | `integration-test-execution`, `e2e-happy-path`, `e2e-failure-paths` |

## Agent Roles

This repo supports these agent invocation types:

- **build**: Generate code, manifests, pipelines, and GitOps overlays
- **review**: Review PRs for quality, security, and governance compliance
- **test**: Write failing tests first (TDD), expand coverage
- **test-execution**: Run all test tiers and validate coverage gates
- **spec**: Convert user intent into structured specifications
- **design**: Translate specs into architecture and component definitions
- **discover**: Pre-spec user research; produce discovery briefs
- **release**: Execute weekly release checklist (CHANGELOG, tag, GitHub Release)

## Artifact Locations

Planning and research artifacts live under `docs/` for discoverability by both humans and AI agents:

| Artifact         | Location                            | Created By     |
| ---------------- | ----------------------------------- | -------------- |
| Specification    | `docs/spec/specification.md`        | spec agent     |
| Technical Design | `docs/design/design.md`             | design agent   |
| Task Plan        | `docs/plan/plan.md`                 | plan agent     |
| Discovery Brief  | `docs/discovery/discovery-brief.md` | discover agent |

## Conventional Commits

All commits **must** follow the Conventional Commits format validated by `reusable-preflight.yml`:

```
type(scope): description (max 72 chars)
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`, `perf`, `build`, `revert`

**Scope:** optional, e.g. `(compute)`, `(dashboards)`, `(alerts)`, `(design)`

**Rules:**
- Subject line: **maximum 72 characters** (including `type(scope):` prefix)
- Use the commit body (blank line + paragraphs) for additional detail
- CI regex: `/^(feat|fix|docs|style|refactor|test|chore|ci|perf|build|revert)(\(.+\))?: .{1,72}$/`

**Common failure — description too long.** If the CI conventional commits check fails, count your subject line characters. 89 characters will fail; shorten to 72.

**Local prevention:** a `commit-msg` pre-commit hook (`scripts/commit-msg.sh`) validates the same regex before the commit is created. Run `pre-commit install --hook-type commit-msg` after cloning to activate it.

**Examples:**
```
feat(compute): implement archetype classifier with wellbeing integration
docs(design): align design doc with spec/plan two-plane architecture
fix: correct DataFrame column ordering in metrics calc
ci: pin actions to SHA in reusable workflows
test(compute): cover all seven archetypes with fixture data
```

## Context Files

| File | Why |
|---|---|
| `docs/PR_STANDARD.md` | PR naming, branch rules, CI requirements |

## §8 — GitOps / Trunk-Based Delivery Contract

### Deployment Lifecycle Gates

1. **Main CI must be green before any PR merges.** Enforced by `main-ci-guard.yml` calling `reusable-main-ci-guard@v1.2.0`.
2. **Observability is built-in.** `job-start` / `job-finish` timestamp steps on all CI jobs for traceability.
3. **All work on short-lived feature branches off `main`.** No direct commits to `main`.
4. **Every PR opens a CI gate.** No bypass without explicit approval.
5. **Rollback is `git revert`.** The `post-deployment.yml` rollback job is a safety net, not the primary mechanism.
