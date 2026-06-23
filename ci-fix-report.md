# CI Fix Report

```
Changed:      10 files modified:
              - compute/metrics.py (1 line: added pragma to dev DSN string)
              - database/init/00-create-databases.sh (1 line: pragma on placeholder pw)
              - database/init/02-dora-roles.sql (1 line: pragma on placeholder pw)
              - database/migrations/001-initial-schema.sql (1 line: pragma on placeholder pw)
              - tests/unit/test_event_schemas.py (6 lines: pragma on test SHAs)
              - tests/unit/test_ingestion_api.py (4 lines: pragma on test SHAs)
              - tests/unit/test_schema.py (1 line: pragma on placeholder pw in SQL)
              - tests/unit/test_worker.py (1 line: pragma on test SHA)
              + end-of-file-fixer added trailing newlines to 4 files
              + prettier/markdownlint auto-formatted 4 files

Validation:   - pre-commit run --all-files: 13/13 hooks PASSED
              - make test-unit: 130/130 tests PASSED
              - make test-integration: not run (requires Docker + TimescaleDB)
              - make test-all: skipped integrate step, unit-only validated

Remaining Risks:
              - GitGuardian is a separate GitHub-integrated check; its findings
                may differ from detect-secrets. Cannot verify locally.
              - The `-- pragma: allowlist secret` syntax is valid for both SQL
                (PostgreSQL line comment) and Python (inside f-strings sent to
                psycopg2). Verify GitGuardian also passes after push.
```
