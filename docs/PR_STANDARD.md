# PR Standard — uFawkesDORA

## Commit Convention

All commits **must** follow Conventional Commits:

```
type(scope): description (max 72 chars)
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`, `perf`, `build`, `revert`

**Scope:** optional, e.g. `(compute)`, `(dashboards)`, `(alerts)`, `(ingestion)`

**Rules:**
- Subject line: **maximum 72 characters** (including `type(scope):` prefix)
- Use the commit body (blank line + paragraphs) for additional detail
- CI regex: `/^(feat|fix|docs|style|refactor|test|chore|ci|perf|build|revert)(\(.+\))?: .{1,72}$/`

## Branch Naming

- `feat/<slug>` — new features
- `fix/<slug>` — bug fixes
- `chore/<slug>` — maintenance, dependencies, tooling
- `docs/<slug>` — documentation only
- `refactor/<slug>` — code restructuring without feature change
- `test/<slug>` — test additions or changes

All branches are short-lived (trunk-based development off `main`).

## CI Requirements

Before a PR can merge:

1. **Main CI must be green.** All jobs in `ci.yml` must pass (preflight, lint, security, build, tests, full-security, dependency-review on PRs).
2. **Main CI Guard** (`main-ci-guard.yml`) verifies the CI pipeline result before merge.
3. **Conventional commits check** — commit messages must match the CC regex.
4. **PR size limit** — diff must be under 400 lines (enforced by preflight).
5. **No unresolved threads** — all review comments must be resolved.
6. **At least one approval** from a code owner.

## PR Title Format

```
type(scope): description
```

Same types as commits. First word after `type(scope):` must be **lowercase**.

## PR Body Requirements

- Description of what and why
- Link to related issue or spec (if applicable)
- Screenshots for UI changes (if applicable)
- Checkbox checklist for CI / review gates
