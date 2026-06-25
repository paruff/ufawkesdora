# CI Diagnosis — PR #18

## Failure 1: Documentation Lint / Markdown Lint + Pre-commit Formatting

| Field        | Value                                                                                                                                                                                                           |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Failure      | Pre-Commit / Documentation Lint / Markdown lint + Validate (pre-commit run --all-files)                                                                                                                         |
| Job          | docs-lint.yml + ci.yml (Validate)                                                                                                                                                                               |
| Evidence     | `docs/plan/plan.md:1257:1 MD004/ul-style Unordered list style [Expected: dash; Actual: plus]` (markdownlint-cli2)                                                                                               |
|              | `Lint Markdown files — files were modified by this hook` (pre-commit markdownlint --fix)                                                                                                                        |
|              | `Format with Prettier — files were modified by this hook` (pre-commit prettier)                                                                                                                                 |
| Location     | `docs/plan/plan.md` line 1257 (MD004), plus table alignment and formatting issues throughout                                                                                                                    |
| Likely Cause | Line 1257 uses `+` at line start (interpreted as unordered list marker `+` style) while `.markdownlint.json` expects `-` style (MD004 default). Prettier found unformatted tables and inconsistent indentation. |
| Confidence   | HIGH                                                                                                                                                                                                            |
| Proposed Fix | Combine lines 1256-1257 into a single line so `+` is not at line start (fixes MD004). Run `prettier --write` on the file to fix all table alignment, comment spacing, and list continuation indentation.        |

## Failure 2: Commit Message Format (Conventional Commits)

| Field        | Value                                                                                                                                                                   |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Failure      | Pre-Commit / Pre-flight Checks / Pre-flight Checks                                                                                                                      |
| Job          | reusable-preflight.yml (Check commit messages step via actions/github-script@v9)                                                                                        |
| Evidence     | `❌ Commit 29abb43: "Revise strategic plan for uFawkesDORA with new metrics"`                                                                                           |
|              | `❌ Commit 85dc09b: "Update plan.md"`                                                                                                                                   |
|              | `❌ 2 commit(s) don't follow Conventional Commits format. Expected: type(scope): description`                                                                           |
| Location     | PR #18 commit history (paruff-patch-1 branch)                                                                                                                           |
| Likely Cause | The first two commits on the branch used free-form messages instead of `type(scope): description` format. The CI regex checks all PR commits (excluding merge commits). |
| Confidence   | HIGH                                                                                                                                                                    |
| Proposed Fix | Squash all commits into a single conventional-commits-compliant commit via `git reset --soft origin/main && git commit -m "type(scope): description"`. Force push.      |
