#!/bin/sh
# ============================================================================
# curl-examples.sh — uFawkesDORA Generic curl Examples
# ----------------------------------------------------------------------------
# Copy-paste-ready curl commands for emitting DORA events to the uFawkesDORA
# ingestion API. Use these in any CI/CD system (Jenkins, GitLab CI, CircleCI,
# Woodpecker, etc.) by substituting the appropriate environment variables.
#
# Environment:
#   DORA_INGESTION_URL   Required. URL of the ingestion API
#   DORA_API_KEY         Optional. Bearer token if auth is enabled
#
# Per-platform CI environment variable mappings:
#
#   Field              GitLab CI              CircleCI              Jenkins                  Woodpecker
#   ─────────────────────────────────────────────────────────────────────────────────────────────────────
#   commit_sha         CI_COMMIT_SHA          CIRCLE_SHA1           GIT_COMMIT               CI_COMMIT_SHA
#   pipeline_url       CI_JOB_URL             CIRCLE_BUILD_URL      BUILD_URL                CI_PIPELINE_URL
#   repo               CI_PROJECT_PATH        CIRCLE_PROJECT_REPONAME  (from GIT_URL)      CI_REPO
#   branch             CI_COMMIT_BRANCH       CIRCLE_BRANCH         BRANCH_NAME              CI_COMMIT_BRANCH
#   service            CI_PROJECT_NAME        CIRCLE_PROJECT_REPONAME  JOB_NAME             CI_REPO_NAME
#
# Reference: events/*.schema.json
# ============================================================================

# ── Prerequisites ──────────────────────────────────────────────────────────
# Set these in your CI/CD environment or shell:
#
#   export DORA_INGESTION_URL="https://dora.example.com"
#   export DORA_API_KEY="changeme"  # pragma: allowlist secret
#
# ────────────────────────────────────────────────────────────────────────────

# ============================================================================
# 1. Deployment Event — Success
# ============================================================================
# Use this when a deployment completes successfully.
#
# CI variable examples:
#   GitLab CI:   CI_COMMIT_SHA, CI_JOB_URL, CI_PROJECT_PATH
#   CircleCI:    CIRCLE_SHA1, CIRCLE_BUILD_URL, CIRCLE_PROJECT_REPONAME
#   Jenkins:     GIT_COMMIT, BUILD_URL, JOB_NAME
#   Woodpecker:  CI_COMMIT_SHA, CI_PIPELINE_URL, CI_REPO
# ============================================================================

# curl -X POST "${DORA_INGESTION_URL}/event" \
#   -H "Content-Type: application/json" \
#   ${DORA_API_KEY:+-H "Authorization: Bearer ${DORA_API_KEY}"} \
#   -d '{
#     "schema_version": "1.0",
#     "event_type": "deployment",
#     "repo": "'"${CI_REPO:-unknown}/${CI_REPO_NAME:-unknown}"'",
#     "service": "'"${CI_REPO_NAME:-unknown}"'",
#     "environment": "production",
#     "commit_sha": "'"${CI_COMMIT_SHA:-unknown}"'",
#     "deployed_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
#     "status": "success",
#     "pipeline_url": "'"${CI_PIPELINE_URL:-}"'"
#   }'

# ============================================================================
# 2. Deployment Event — Failed
# ============================================================================
# Use this when a deployment fails (rollback, error, etc.).

# curl -X POST "${DORA_INGESTION_URL}/event" \
#   -H "Content-Type: application/json" \
#   ${DORA_API_KEY:+-H "Authorization: Bearer ${DORA_API_KEY}"} \
#   -d '{
#     "schema_version": "1.0",
#     "event_type": "deployment",
#     "repo": "'"${CI_REPO:-unknown}/${CI_REPO_NAME:-unknown}"'",
#     "service": "'"${CI_REPO_NAME:-unknown}"'",
#     "environment": "production",
#     "commit_sha": "'"${CI_COMMIT_SHA:-unknown}"'",
#     "deployed_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
#     "status": "failed",
#     "pipeline_url": "'"${CI_PIPELINE_URL:-}"'"
#   }'

# ============================================================================
# 3. Incident Event — Opened
# ============================================================================
# Use this when a production incident is declared (pager fires).

# curl -X POST "${DORA_INGESTION_URL}/event" \
#   -H "Content-Type: application/json" \
#   ${DORA_API_KEY:+-H "Authorization: Bearer ${DORA_API_KEY}"} \
#   -d '{
#     "schema_version": "1.0",
#     "event_type": "incident",
#     "repo": "my-org/'"${CI_REPO_NAME:-my-service}"'",
#     "service": "'"${CI_REPO_NAME:-my-service}"'",
#     "incident_id": "INC-'"$(date +%s)"'",
#     "status": "opened",
#     "reported_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
#     "severity": "critical"
#   }'

# ============================================================================
# 4. Incident Event — Resolved
# ============================================================================
# Use this when an incident is resolved. FDRT = time between opened and resolved.
# IMPORTANT: Use the SAME incident_id that was used in the "opened" event.

# curl -X POST "${DORA_INGESTION_URL}/event" \
#   -H "Content-Type: application/json" \
#   ${DORA_API_KEY:+-H "Authorization: Bearer ${DORA_API_KEY}"} \
#   -d '{
#     "schema_version": "1.0",
#     "event_type": "incident",
#     "repo": "my-org/'"${CI_REPO_NAME:-my-service}"'",
#     "service": "'"${CI_REPO_NAME:-my-service}"'",
#     "incident_id": "INC-1743206400",
#     "status": "resolved",
#     "resolved_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
#     "severity": "critical"
#   }'

# ============================================================================
# 5. Rework Event — Hotfix
# ============================================================================
# Use this when a user-visible hotfix or rollback is deployed.
# user_visible=true means this counts toward the Rework Rate metric.

# curl -X POST "${DORA_INGESTION_URL}/event" \
#   -H "Content-Type: application/json" \
#   ${DORA_API_KEY:+-H "Authorization: Bearer ${DORA_API_KEY}"} \
#   -d '{
#     "schema_version": "1.0",
#     "event_type": "rework",
#     "repo": "'"${CI_REPO:-unknown}/${CI_REPO_NAME:-unknown}"'",
#     "service": "'"${CI_REPO_NAME:-unknown}"'",
#     "rework_type": "hotfix",
#     "user_visible": true,
#     "deployment_sha": "'"${CI_COMMIT_SHA:-unknown}"'",
#     "deployed_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
#     "description": "Hotfix deployed"
#   }'

# ============================================================================
# 6. PR Event — Merged
# ============================================================================
# Use this when a pull request is merged. Lead Time = merge time - first commit.
# Note: Some CI systems don't expose first_commit_at — set it manually if known.

# curl -X POST "${DORA_INGESTION_URL}/event" \
#   -H "Content-Type: application/json" \
#   ${DORA_API_KEY:+-H "Authorization: Bearer ${DORA_API_KEY}"} \
#   -d '{
#     "schema_version": "1.0",
#     "event_type": "pr",
#     "repo": "'"${CI_REPO:-unknown}/${CI_REPO_NAME:-unknown}"'",
#     "service": "'"${CI_REPO_NAME:-unknown}"'",
#     "pr_number": 42,
#     "status": "merged",
#     "commit_sha": "'"${CI_COMMIT_SHA:-unknown}"'",
#     "occurred_at": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
#     "first_commit_at": "2026-06-22T10:00:00Z",
#     "source": "curl-examples"
#   }'

# ============================================================================
# Verifying events reached the database
# ============================================================================
# After sending events, verify they arrived by querying the raw_events table:
#
#   docker compose -f docker-compose.dev.yml exec -T timescaledb \
#     psql -U postgres -d dora_metrics \
#     -c "SELECT event_type, status, COUNT(*) FROM raw_events GROUP BY event_type, status;"
#
# Or for the latest events:
#
#   docker compose -f docker-compose.dev.yml exec -T timescaledb \
#     psql -U postgres -d dora_metrics \
#     -c "SELECT recorded_at, event_type, status FROM raw_events ORDER BY recorded_at DESC LIMIT 10;"

# ============================================================================
# Troubleshooting
# ============================================================================
#
# Problem: curl: (6) Could not resolve host
#   Fix: Check DORA_INGESTION_URL — include https:// prefix
#
# Problem: HTTP 422
#   Fix: The JSON payload failed schema validation. Check event_type spelling
#        and required fields. Reference events/*.schema.json
#
# Problem: HTTP 401 or 403
#   Fix: Set DORA_API_KEY if the ingestion API requires authentication
#
# Problem: HTTP 500
#   Fix: Check the ingestion API logs. The /event endpoint may be down.
#
# Problem: "command not found: curl"
#   Fix: Install curl in your CI runner or use a Docker image with curl
#        (e.g., curlimages/curl:latest)
