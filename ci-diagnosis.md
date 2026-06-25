# CI Diagnosis — PIPE-003 PR #22

| Field | Value |
|-------|-------|
| **Failure** | Pre-Commit / Unit Tests — `test_use_official_actions` |
| **Location** | `tests/unit/test_workflow_validation.py:100` |
| **Evidence** | `AssertionError: scheduled.yml job 'pre-commit-autoupdate' uses non-standard action: peter-evans/create-pull-request@v6` |
| **Likely Cause** | `peter-evans/` is not in the `allowed_actions` list in `test_use_official_actions` |
| **Confidence** | HIGH |
| **Proposed Fix** | Add `"peter-evans/"` to `allowed_actions` list in `test_workflow_validation.py:74-88` |
