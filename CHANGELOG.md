# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-24

### Added
- Initial scaffold of the uFawkesDORA metrics platform.
- Canonical JSON schemas for Draft-07 deployment and incident events.
- Ingestion API built with FastAPI and asyncpg for stateless, high-throughput event queuing.
- Async queue processor (Worker) utilizing `SELECT ... FOR UPDATE SKIP LOCKED` for concurrent safe dequeuing.
- DORA metrics compute engine calculating Deployment Frequency, Lead Time, Change Failure Rate, Time to Restore, and Rework Rate.
- Comprehensive CI Pipeline covering linting, security, dependency reviews, unit/integration/smoke/E2E testing, and a coverage quality gate at 80%.
- Minimum standard README with architectural diagrams, status, capability mappings, quickstart guide, and suite context.
