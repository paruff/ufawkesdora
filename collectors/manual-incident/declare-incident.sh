#!/bin/sh
# ============================================================================
# declare-incident.sh — uFawkesDORA Manual Incident Declaration
# ----------------------------------------------------------------------------
# Run this script when you are paged for a production incident to emit an
# incident-opened event to the uFawkesDORA ingestion API.
#
# Usage:
#   # Interactive mode (prompts for each field)
#   ./declare-incident.sh
#
#   # Flag mode (non-interactive, for automation)
#   ./declare-incident.sh --incident_id=INC-123 --service=my-service --severity=critical
#
# Environment:
#   DORA_INGESTION_URL   Required. URL of the ingestion API (e.g. https://dora.example.com)
#   DORA_API_KEY         Optional. API key if auth is enabled on the ingestion API
#
# Exit codes:
#   0 — Incident event accepted (HTTP 201)
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
OCCURRED_AT=""

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
            echo "Usage: $0 [--incident_id=ID] [--service=NAME] [--severity=critical|major|minor]"
            exit 0
            ;;
        *)
            echo "[dora] ERROR: Unknown option: $1" >&2
            echo "[dora] Usage: $0 [--incident_id=ID] [--service=NAME] [--severity=critical|major|minor]" >&2
            exit 1
            ;;
    esac
    shift
done

# ── Interactive prompts (fallback when flags are missing) ───────────────────

if [ -z "$INCIDENT_ID" ]; then
    printf "Incident ID (e.g. INC-123): "
    read -r INCIDENT_ID
fi

if [ -z "$SERVICE" ]; then
    printf "Service name (e.g. api-gateway): "
    read -r SERVICE
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

if [ -z "$SERVICE" ]; then
    echo "[dora] ERROR: service is required" >&2
    exit 1
fi

# Validate severity
case "$SEVERITY" in
    critical|major|minor) ;;
    *)
        echo "[dora] ERROR: severity must be one of: critical, major, minor (got: $SEVERITY)" >&2
        exit 1
        ;;
esac

# ── Build payload ───────────────────────────────────────────────────────────

OCCURRED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

PAYLOAD=$(cat <<EOF
{
  "schema_version": "1.0",
  "event_type": "incident",
  "repo": "unknown/${SERVICE}",
  "service": "${SERVICE}",
  "incident_id": "${INCIDENT_ID}",
  "status": "opened",
  "occurred_at": "${OCCURRED_AT}",
  "severity": "${SEVERITY}"
}
EOF
)

# ── Send event ─────────────────────────────────────────────────────────────

echo "[dora] Declaring incident ${INCIDENT_ID} on ${SERVICE}..."

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "${INGESTION_URL}/event" \
    -H "Content-Type: application/json" \
    ${API_KEY:+-H "Authorization: Bearer ${API_KEY}"} \
    -d "${PAYLOAD}")

if [ "${HTTP_STATUS}" = "201" ]; then
    echo "[dora] ✅ Incident ${INCIDENT_ID} declared successfully"
    echo "[dora]    Service: ${SERVICE}"
    echo "[dora]    Severity: ${SEVERITY}"
    echo "[dora]    Occurred at: ${OCCURRED_AT}"
    echo "[dora]    API: ${INGESTION_URL}/event"
    exit 0
else
    echo "[dora] ❌ Failed to declare incident (HTTP ${HTTP_STATUS})" >&2
    echo "[dora]    Check DORA_INGESTION_URL and network connectivity" >&2
    exit 1
fi
