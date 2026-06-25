Failure:      Architecture/Design doc warning
Location:     .github/workflows/reusable-tests.yml:424
Evidence:     Warning: ARCHITECTURE.md not found (check docs/ too)
Likely Cause: The repository uses docs/design/design.md and docs/spec/specification.md instead of ARCHITECTURE.md.
Confidence:   HIGH
Proposed Fix: Update required-files check in reusable-tests.yml to also check for docs/design/design.md and docs/spec/specification.md.
