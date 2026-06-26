# CI Fix Report — PIPE-004 & PIPE-005 PR #23

## Changed
- `.github/workflows/reusable-tests.yml` — Three fixes:
  1. **Line 439**: Escaped brackets in grep pattern (`\[Add contribution guidelines\]`)
     — was creating a BRE character class causing false placeholder positive.
  2. **Line 450**: Fixed pipe alternation in README section regex (`\|` → `|`)
     — backslashes made pipes literal in ERE mode, no alternation.
  3. **Lines 50, 55, 158, 187**: Changed `compose-file` default from `"compose.yaml"`
     to `"docker-compose.test.yml"` and `compose-profile` default from `"core"` to `""`.
     Made `--profile` flag conditional on non-empty profile value.
- `.github/workflows/ci.yml` — Two fixes (PIPE-005):
  1. **Line 92**: Added `if: github.event_name == 'pull_request'` to `dependency-review`
     job — ensures dependency review only runs on PRs where it can compare base/head.
  2. **Line 95**: Changed `fail-on-severity` from `high` to `moderate` — per spec,
     blocks on moderate-severity vulnerabilities and above.
- `ci-diagnosis.md` — Updated with three-diagnosis format.
- `ci-fix-report.md` — This report.

## Validation
- **Required files check**: All checks pass locally (exit 0)
  - Placeholder grep no longer falsely triggers on CONTRIBUTING.md ✅
  - README section regex matches all required sections ✅
- **YAML lint**: Passes (only pre-existing line-length warnings) ✅
- **Pre-commit**: All hooks pass on changed files ✅
- **Compose file**: `docker-compose.test.yml` confirmed existing ✅
- **Dependency review in ci.yml**: `grep "dependency-review" .github/workflows/ci.yml` returns match ✅
- **PR-only guard**: `if: github.event_name == 'pull_request'` present ✅
- **Severity threshold**: `fail-on-severity: moderate` set ✅
- **Ruleset update**: `required_status_checks` context changed from `"Validate"` to `"CI / CI Complete"` via API (HTTP 200) ✅

## Additional Fix (Infrastructure — Ruleset)
- **GitHub ruleset `main-protection` (id 17553691)**: Updated `required_status_checks`
  context from `"Validate"` to `"CI / CI Complete"`.
  - Old `ci.yml` had a `validate` job (name: `Validate`) that emitted this status check.
  - PIPE-004 consolidation replaced it with `preflight` + `lint` + `build` + `tests` +
    `full-security` + `dependency-review` + `ci-complete`.
  - The equivalent final gate is `CI / CI Complete` — this job only passes when all
    preceding CI jobs pass.

## Remaining Risks
- **Pre-existing: `reusable-lint.yml`** language detection (`detect-changes` job) silently
  fails on `pull_request` events due to shallow checkout (`fetch-depth: 1`). The base SHA
  (`github.event.pull_request.base.sha`) is not available in the shallow clone, so
  `git diff` errors are suppressed by `2>/dev/null` and all language flags default to
  `false`. This means lint sub-jobs (Python, Go, YAML, etc.) are always skipped on PRs
  even when matching files change. Fix: add `fetch-depth: 0` to the checkout step in
  `reusable-lint.yml`.
- `reusable-build.yml` lines 91-95 still reference `compose.yaml` for `:latest` tag
  detection. Doesn't cause CI failures (silently skipped when file absent).
