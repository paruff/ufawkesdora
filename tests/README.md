# Tests

## Structure

```
tests/
├── unit/           # Fast unit tests (no Docker required)
│   ├── conftest.py           # Shared fixtures and helpers
│   ├── test_ingestion_api.py # API endpoint validation
│   ├── test_event_schemas.py # Event schema validation
│   ├── test_metrics.py       # Metrics computation logic
│   ├── test_queue.py         # Queue operations
│   ├── test_validator.py     # Input validation edge cases
│   ├── test_worker.py        # Worker process logic
│   └── test_*.py             # Additional test modules
└── integration/    # Integration tests (require Docker)
    ├── test_e2e_flow.py              # End-to-end pipeline
    ├── test_metrics_integration.py   # Metrics with real DB
    └── test_schema.py                # Database schema validation
```

## Running Tests

| Tier        | Command                 | Requires Docker | Approx. time |
| ----------- | ----------------------- | --------------- | ------------ |
| Unit        | `make test-unit`        | No              | ~3 s         |
| Integration | `make test-integration` | Yes             | ~30 s        |
| All         | `make test-all`         | Mixed           | ~35 s        |
| Coverage    | `make test-coverage`    | No              | ~5 s         |

## Writing Tests

- **Unit tests** must never require Docker. Mock all external resources (database connections, HTTP calls, Pushgateway).
- **Integration tests** use Docker Compose files (`docker-compose.integration.yml`, `docker-compose.test.yml`) or testcontainers to spin up required infrastructure.
- **Coverage gate**: Unit test coverage must meet the 80% threshold configured in the CI pipeline (`--cov-fail-under=80`).
