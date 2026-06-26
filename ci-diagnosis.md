Failure:      Tests / Required files — CONTRIBUTING.md false placeholder positive
Location:     .github/workflows/reusable-tests.yml:439
Evidence:     grep pattern `[Add contribution ...]` in BRE mode creates a
              character class matching any line containing common letters.
              This causes a false positive "CONTRIBUTING.md is still a placeholder"
              and exits with code 1.
Likely Cause: Brackets need escaping as `\[` and `\]` for grep BRE mode.
              The unescaped character class matches almost any line.
Confidence:   HIGH
Proposed Fix: Add backslash escapes before [ and ] in line 439.

---
Failure:      Tests / Required files — README.md section regex uses wrong escaping
Location:     .github/workflows/reusable-tests.yml:450
Evidence:     grep -qE "## Quick Start\|Getting Started\|## Install" README.md
              The \\| in ERE mode means literal pipe, not alternation.
              README.md has "## Quick Start" but fails to match due to wrong regex.
Likely Cause: In ERE mode (-E), alternation is "|" not "\\|". The backslashes
              make the pipes literal characters.
Confidence:   HIGH
Proposed Fix: Remove backslashes before | on line 450 (change \\| to |).

---
Failure:      Tests / Compose Smoke — compose.yaml not found
Location:     .github/workflows/reusable-tests.yml:55
Evidence:     docker compose -f compose.yaml --profile core up -d --build
              Error: open compose.yaml: no such file or directory
Likely Cause: Default compose-file input is "compose.yaml" but the repo uses
              docker-compose.test.yml / docker-compose.integration.yml / docker-compose.dev.yml.
Confidence:   HIGH
Proposed Fix: Change default compose-file from "compose.yaml" to "docker-compose.test.yml".

---

Failure:      PR #23 blocked — "ValidateExpected" required check never reports
Location:     GitHub ruleset `main-protection` (id 17553691)
Evidence:     Ruleset requires status check context "Validate" but no workflow emits it.
               Old ci.yml had a `validate` job (name: Validate) that was replaced by
               preflight/lint/build/tests/etc. during PIPE-004 consolidation.
               PR shows: "ValidateExpected — Waiting for status to be reported" (Required).
Likely Cause: PIPE-004 consolidation removed the old `validate` job. The `main-protection`
              ruleset still requires its check context `"Validate"` to pass.
Confidence:   HIGH
Proposed Fix: Update ruleset via API: change required_status_checks context from
              `"Validate"` to `"CI / CI Complete"` (the new final pipeline gate).
