# CI Fix Report — PIPE-004 PR #23

## Changed
- `.github/workflows/reusable-tests.yml` — Three fixes:
  1. **Line 439**: Escaped brackets in grep pattern (`\[Add contribution guidelines\]`)
     — was creating a BRE character class causing false placeholder positive.
  2. **Line 450**: Fixed pipe alternation in README section regex (`\|` → `|`)
     — backslashes made pipes literal in ERE mode, no alternation.
  3. **Lines 50, 55, 158, 187**: Changed `compose-file` default from `"compose.yaml"`
     to `"docker-compose.test.yml"` and `compose-profile` default from `"core"` to `""`.
     Made `--profile` flag conditional on non-empty profile value.
- `ci-diagnosis.md` — Updated with three-diagnosis format.
- `ci-fix-report.md` — This report.

## Validation
- **Required files check**: All checks pass locally (exit 0)
  - Placeholder grep no longer falsely triggers on CONTRIBUTING.md ✅
  - README section regex matches all required sections ✅
- **YAML lint**: Passes (only pre-existing line-length warnings) ✅
- **Pre-commit**: All hooks pass on changed files ✅
- **Compose file**: `docker-compose.test.yml` confirmed existing ✅

## Remaining Risks
- `reusable-build.yml` lines 91-95 still reference `compose.yaml` for `:latest` tag
  detection. This doesn't cause CI failures (silently skipped when file absent),
  but should be updated in a future PR to check actual compose files.
