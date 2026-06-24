# Contributing to uFawkesDORA

First off, thank you for taking the time to contribute!

This project adheres to the uFawkes engineering standards. Please review the guidelines below to ensure a smooth contribution process.

## 1. Development Workflow

We use a standard branching and pull request workflow:

1. **Fork/Branch**: Create a feature branch off of `main` (e.g., `feat/my-new-feature` or `fix/some-bug`).
2. **Conventional Commits**: Write commit messages that adhere to [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) format (e.g., `feat(api): add team crud endpoints` or `fix(worker): handle connection drop gracefully`).
3. **Pre-commit Hooks**: Run pre-commit hooks locally to format and lint before staging:
   ```bash
   pre-commit run --all-files
   ```
4. **Pull Request**: Open a PR against `main`. All CI checks must pass before merging.

## 2. Coding Standards

- **Python**: Follow PEP 8 style guide. We enforce formatting via `ruff-format` (Black compatible) and linting via `ruff`.
- **Typing**: Use static typing where possible. Run `mypy` or similar type checking to verify type safety.
- **Asynchronous Patterns**: Use `asyncpg` context managers cleanly. Ensure all mocked async objects use explicit `__aenter__` / `__aexit__` or correct async decorators.
- **Database Queries**: Write idempotent database init scripts (`IF NOT EXISTS` / `CREATE OR REPLACE`). Use parameterized queries to prevent SQL injection.

## 3. Testing Requirements

We maintain a strict testing and quality bar:

- **Unit Tests**: Place in `tests/unit/`. Unit tests must be extremely fast, pure, and **never require a running Docker container**. Mock all external resources (database, pushgateway, HTTP endpoints).
- **Integration Tests**: Place in `tests/integration/`. Use Docker Compose or testcontainers to orchestrate a live TimescaleDB database or test environment.
- **Quality Gate**: Code coverage must meet or exceed the **80% threshold** as measured by `pytest-cov` in CI. Ensure your feature is thoroughly tested.
