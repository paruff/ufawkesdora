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
