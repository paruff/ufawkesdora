#!/bin/bash
# ============================================================================
# 00-create-databases.sh
# ----------------------------------------------------------------------------
# Creates the dora_metrics, infisical, and defectdojo databases with
# least-privilege roles. Idempotent — safe to re-run.
#
# This script runs via psql as the postgres superuser during container init.
# It does NOT use environment variables for credentials.
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Create databases (idempotent via exception-safe DO blocks)
# ---------------------------------------------------------------------------
create_database_if_not_exists() {
    local db_name="$1"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '${db_name}') THEN
                CREATE DATABASE "${db_name}";
                RAISE NOTICE 'Created database: ${db_name}';
            ELSE
                RAISE NOTICE 'Database already exists: ${db_name}';
            END IF;
        END
        \$\$;
EOSQL
}

# ---------------------------------------------------------------------------
# Create roles (idempotent via exception-safe DO blocks)
# ---------------------------------------------------------------------------
create_role_if_not_exists() {
    local role_name="$1"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${role_name}') THEN
                CREATE ROLE "${role_name}" WITH LOGIN PASSWORD 'change_me_in_production';
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
