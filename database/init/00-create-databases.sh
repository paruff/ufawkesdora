#!/bin/bash
# ============================================================================
# 00-create-databases.sh
# ----------------------------------------------------------------------------
# Creates the dora_metrics, infisical, and defectdojo databases with
# least-privilege roles. Idempotent — safe to re-run.
#
# This script runs via psql as the postgres superuser during container init.
# It does NOT use environment variables for credentials.
#
# IMPORTANT: CREATE DATABASE cannot run inside a transaction/DO block,
# so we use shell-level conditionals with psql -tAc for database checks.
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Create databases (idempotent — checked at shell level)
# ---------------------------------------------------------------------------
create_database_if_not_exists() {
    local db_name="$1"
    local exists
    exists=$(psql -tAc "SELECT 1 FROM pg_database WHERE datname='${db_name}'" 2>/dev/null || true)
    if [ "$exists" != "1" ]; then
        echo "Creating database: ${db_name}"
        psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${db_name}\""
    else
        echo "Database already exists: ${db_name}"
    fi
}

# ---------------------------------------------------------------------------
# Create roles (idempotent via exception-safe DO blocks — roles CAN be
# created inside a function, so DO blocks work fine here)
# ---------------------------------------------------------------------------
create_role_if_not_exists() {
    local role_name="$1"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${role_name}') THEN
                CREATE ROLE "${role_name}" WITH LOGIN PASSWORD 'change_me_in_production';  -- pragma: allowlist secret
                RAISE NOTICE 'Created role: ${role_name}';
            ELSE
                RAISE NOTICE 'Role already exists: ${role_name}';
            END IF;
        END
        \$\$;
EOSQL
}

echo "=== 00-create-databases.sh: Creating databases ==="

create_database_if_not_exists "dora_metrics"
create_database_if_not_exists "infisical"
create_database_if_not_exists "defectdojo"

echo "=== 00-create-databases.sh: Creating roles ==="

create_role_if_not_exists "dora_app"
create_role_if_not_exists "infisical_app"
create_role_if_not_exists "defectdojo_app"

echo "=== 00-create-databases.sh: Complete ==="
