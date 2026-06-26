#!/usr/bin/env bash
# commit-msg.sh — validate Conventional Commits format
# Mirrors the regex in .github/workflows/reusable-preflight.yml
# Installed as a pre-commit hook in the commit-msg stage.
#
# Format: type(scope): description (1-72 chars)
# Types:  feat, fix, docs, style, refactor, test, chore, ci, perf, build, revert
# Scope is optional. Description max 72 characters.
#
# If this hook rejects your message, shorten the description.
# Put extra detail in the commit body (blank line, then body text).

set -euo pipefail

COMMIT_MSG_FILE="$1"

# Read the first line (subject)
read -r SUBJECT < "$COMMIT_MSG_FILE"

# Allow fixup/squash commits created by git rebase --autosquash
if [[ "$SUBJECT" =~ ^(fixup!|squash!) ]]; then
  exit 0
fi

# Allow merge commits
if [[ "$SUBJECT" =~ ^Merge[[:space:]] ]]; then
  exit 0
fi

# Conventional Commits regex (mirrors reusable-preflight.yml line 150)
CONVENTIONAL_REGEX='^(feat|fix|docs|style|refactor|test|chore|ci|perf|build|revert)(\(.+\))?: .{1,72}$'

if ! echo "$SUBJECT" | grep -qE "$CONVENTIONAL_REGEX"; then
  echo ""
  echo "❌ Commit message does not follow Conventional Commits format:"
  echo "   \"$SUBJECT\""
  echo ""
  echo "Required format: type(scope): description (1-72 chars)"
  echo "  Types:  feat, fix, docs, style, refactor, test, chore, ci, perf, build, revert"
  echo "  Scope:  optional, e.g. (compute), (dashboards), (alerts)"
  echo "  Description: 1-72 characters on the subject line"
  echo ""
  echo "Tips if failing:"
  echo "  - Shorten the description to 72 chars or fewer"
  echo "  - Put detailed explanation in the commit body (blank line after subject)"
  echo "  - Subject line character count: $(echo -n "$SUBJECT" | wc -c | tr -d ' ')"
  echo ""
  echo "Example valid messages:"
  echo "  feat(compute): implement archetype classifier"
  echo "  docs(design): align with spec/plan two-plane architecture"
  echo "  fix: correct DataFrame column ordering in metrics calc"
  exit 1
fi

exit 0
