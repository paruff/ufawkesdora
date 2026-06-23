#!/bin/sh
# ============================================================================
# resolve-incident.sh — uFawkesDORA Manual Incident Resolution
# ----------------------------------------------------------------------------
# Run this script when an incident has been resolved to emit an
# incident-resolved event to the uFawkesDORA ingestion API.
#
# This is needed for FDRT (Failure Deployment Recovery Time) calculation.
# FDRT measures the gap between incident-opened and incident-resolved.
#
# Usage:
#   # Interactive mode
#   ./resolve-incident.sh
#
#   # Flag mode
#   ./resolve-incident.sh --incident_id=INC-123
#
# Environment:
#   DORA_INGESTION_URL   Required. URL of the ingestion API
#   DORA_API_KEY         Optional. API key if auth is enabled
#
# Exit codes:
#   0 — Resolution event accepted (HTTP 201)
#   1 — Failed (missing fields, network error, non-201 response)
#
# Reference: events/incident-event.schema.json
# ============================================================================

set -u

# ── Defaults ────────────────────────────────────────────────────────────────

INGESTION_URL="${DORA_INGESTION_URL:-}"
API_KEY="${DORA_API_KEY:-}"
INCIDENT_ID=""
SERVICE=""
SEVERITY=""

# ── Flag parsing ────────────────────────────────────────────────────────────

while [ $# -gt 0 ]; do
    case "$1" in
        --incident_id=*)
            INCIDENT_ID="${1#*=}"
            ;;
        --service=*)
            SERVICE="${1#*=}"
            ;;
        --severity=*)
            SEVERITY="${1#*=}"
            ;;
        --help)
            echo "Usage: $0 --incident_id=ID [--service=NAME] [--severity=LEVEL]"
            exit 0
            ;;
        *)
            echo "[dora] ERROR: Unknown option: $1" >&2
            echo "[dora] Usage: $0 --incident_id=ID [--service=NAME] [--severity=LEVEL]" >&2
            exit 1
            ;;
    esac
    shift
done

# ── Interactive prompts ─────────────────────────────────────────────────────

if [ -z "$INCIDENT_ID" ]; then
    printf "Incident ID to resolve (e.g. INC-123): "
    read -r INCIDENT_ID
fi

if [ -z "$SERVICE" ]; then
    printf "Service name (e.g. api-gateway) [unknown]: "
    read -r SERVICE
    [ -z "$SERVICE" ] && SERVICE="unknown"
fi

if [ -z "$SEVERITY" ]; then
    printf "Severity (critical/major/minor) [critical]: "
    read -r SEVERITY
    [ -z "$SEVERITY" ] && SEVERITY="critical"
fi

# ── Validation ──────────────────────────────────────────────────────────────

if [ -z "$INGESTION_URL" ]; then
    echo "[dora] ERROR: DORA_INGESTION_URL is not set" >&2
    echo "[dora] Set it as an environment variable or in a .env file" >&2
    exit 1
fi

if [ -z "$INCIDENT_ID" ]; then
    echo "[dora] ERROR: incident_id is required" >&2
    exit 1
fi

case "$SEVERITY" in
    critical|major|minor) ;;
    *)
        echo "[dora] ERROR: severity must be one of: critical, major, minor (got: $SEVERITY)" >&2
        exit 1
        ;;
esac

# ── Build payload ───────────────────────────────────────────────────────────

RESOLVED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

PAYLOAD=$(cat <<EOF
{
  "schema_version": "1.0",
  "event_type": "incident",
  "repo": "unknown/${SERVICE}",
  "service": "${SERVICE}",
  "incident_id": "${INCIDENT_ID}",
  "status": "resolved",
  "resolved_at": "${RESOLVED_AT}",
  "severity": "${SEVERITY}"
}
EOF
)

# ── Send event ─────────────────────────────────────────────────────────────

echo "[dora] Resolving incident ${INCIDENT_ID}..."

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "${INGESTION_URL}/event" \
    -H "Content-Type: application/json" \
    ${API_KEY:+-H "Authorization: Bearer ${API_KEY}"} \
    -d "${PAYLOAD}")

if [ "${HTTP_STATUS}" = "201" ]; then
    echo "[dora] ✅ Incident ${INCIDENT_ID} resolved successfully"
    echo "[dora]    Service: ${SERVICE}"
    echo "[dora]    Resolved at: ${RESOLVED_AT}"
    echo "[dora]    API: ${INGESTION_URL}/event"
    exit 0
else
    echo "[dora] ❌ Failed to resolve incident (HTTP ${HTTP_STATUS})" >&2
    echo "[dora]    Check DORA_INGESTION_URL and network connectivity" >&2
    exit 1
fi
