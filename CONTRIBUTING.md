# Contributing to uFawkesDORA

First off, thank you for taking the time to contribute!

This project adheres to the uFawkes engineering standards. Please review the guidelines below to ensure a smooth contribution process.

## 1. Development Workflow

This project enforces a strict GitOps development workflow. Direct commits or pushes to the `main` branch are prohibited; **all changes must go through a pull request and be verified by the CI pipeline before merging**.

### Branching & PR Strategy

1. **Branch**: Create a feature or bugfix branch off of `main` (e.g., `feat/my-new-feature` or `fix/some-bug`).
2. **Local Checks**: Run pre-commit hooks locally before staging or committing:
   ```bash
   pre-commit run --all-files
   ```
3. **PR Creation**: Open a Pull Request (PR) from your branch against `main`.
4. **Verification**: The 5-Phase pipeline (Pre-Commit → Post-Commit → Pre-Deployment → Deploy → Post-Deployment) executes on your PR. All checks in Phase 1 (Pre-Commit), Phase 2 (Post-Commit), and Phase 3 (Pre-Deployment) must pass before the PR is mergeable.
5. **No Direct Commits**: Never push or commit directly to `main`. Merging a PR is the only way code reaches `main`.

### PR Size Limit

We encourage keeping pull requests small and focused. The CI pipeline warns when a PR exceeds **400 lines changed** (additions + deletions). This is a **non-blocking guidance** — large PRs still pass CI — but a comment is posted to encourage splitting into smaller chunks.

- **Limit**: 400 lines changed
- **Behavior**: Warning only (does not block the PR)
- **Override**: Apply the `large-pr-approved` label to suppress the warning
- **Emergency bypass**: Apply the `emergency-bypass` label to skip all preflight checks

### Commit Message Guidelines

We enforce the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) format for all commits. A pre-flight validator runs in CI to verify adherence. Commits with invalid structures or descriptions that are too long will fail the pipeline.

**Format Pattern**: `<type>(<scope>): <description>`

- **Commit Types**:
  - `feat`: A new feature
  - `fix`: A bug fix
  - `refactor`: Code change that neither fixes a bug nor adds a feature
  - `docs`: Documentation-only changes
  - `test`: Adding missing tests or correcting existing tests
  - `style`: Changes that do not affect the meaning of the code (whitespace, formatting, missing semi-colons, etc.)
  - `ci`: Changes to CI/CD configuration files and scripts
  - `build`: Changes that affect the build system or external dependencies
- **Character Limit**: The description (the text after `<type>(<scope>):` or `<type>:`) **must not exceed 72 characters**. Keep descriptions short, concise, and descriptive.
- **Example Valid Messages**:
  - `feat(api): add team crud endpoints`
  - `fix(pipeline): restore integration tests, move unit to pre-commit`

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
