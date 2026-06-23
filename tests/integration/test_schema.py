"""Unit tests for the uFawkesDORA database schema.

Spins up a real TimescaleDB container via testcontainers, applies all init
scripts, and validates:
- All 6 tables exist
- 3 hypertables are properly created
- dora_app role exists with correct (non-superuser) permissions
- Role grants match expected table-level privileges
"""

import re
from pathlib import Path

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer


# ── Helpers ────────────────────────────────────────────────────────────────────


def find_repo_root() -> Path:
    """Walk up from this file's directory to find the repo root."""
    current = Path(__file__).resolve().parent
    while current.name != "ufawkesdora" and current.parent != current:
        current = current.parent
    assert current.name == "ufawkesdora", f"Could not find repo root from {__file__}"
    return current


def execute_sql_file(cursor, filepath: Path, dbname: str = None):
    """Read a SQL file and execute it via psycopg2.

    Handles:
    - ``\\c dbname`` meta-commands (switches database)
    - Multiple statements separated by semicolons
    - Dollar-quoted strings ($$...$$)
    - Idempotent IF NOT EXISTS patterns
    """
    content = filepath.read_text()

    # Handle \c dbname meta-command (connect to another database)
    if dbname is None:
        m = re.search(r'^\\c\s+(\w+)', content, re.MULTILINE)
        if m:
            content = re.sub(r'^\\c\s+\w+\s*', '', content, flags=re.MULTILINE)

    # Split by semicolons but respect dollar-quoting and string literals
    statements = split_sql_statements(content)

    for stmt in statements:
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            cursor.execute(stmt)
        except Exception as e:
            raise RuntimeError(
                f"Error executing statement from {filepath.name}:\n"
                f"{stmt[:200]}...\n"
                f"Error: {e}"
            ) from e


def split_sql_statements(sql: str) -> list[str]:
    """Split SQL text into individual statements, respecting dollar-quoting."""
    statements = []
    current = []
    depth = 0
    in_dollar = False
    dollar_tag = None
    in_string = False
    string_char = None

    i = 0
    while i < len(sql):
        ch = sql[i]

        # Track dollar-quoting: $$...$$ or $tag$...$tag$
        if not in_string and not in_dollar:
            if ch == '$':
                j = i + 1
                tag_chars = []
                while j < len(sql) and sql[j] != '$':
                    tag_chars.append(sql[j])
                    j += 1
                if j < len(sql) and sql[j] == '$':
                    tag = ''.join(tag_chars)
                    if dollar_tag is None:
                        dollar_tag = tag
                        in_dollar = True
                        current.append(sql[i:j+1])
                        i = j + 1
                        continue
                    elif tag == dollar_tag:
                        dollar_tag = None
                        in_dollar = False
                        current.append(sql[i:j+1])
                        i = j + 1
                        continue

        # Track single/double-quoted strings
        if not in_dollar:
            if ch in ("'", '"') and not in_string:
                in_string = True
                string_char = ch
            elif ch == string_char and in_string:
                # Check for escaped quote
                if i + 1 < len(sql) and sql[i + 1] == string_char:
                    current.append(ch)
                    current.append(ch)
                    i += 2
                    continue
                in_string = False
                string_char = None

        # Track dollar-quoting within strings is irrelevant

        # Split on semicolons (top-level only)
        if ch == ';' and not in_string and not in_dollar:
            current.append(ch)
            stmt = ''.join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    # Remainder
    remaining = ''.join(current).strip()
    if remaining:
        statements.append(remaining)

    return statements


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def schema_dir() -> Path:
    """Return the path to the database/ directory."""
    return find_repo_root() / "database"


@pytest.fixture(scope="module")
def postgres_container() -> PostgresContainer:
    """Start a TimescaleDB container for testing."""
    container = PostgresContainer(
        image="timescale/timescaledb:latest-pg16",
        driver="psycopg2",
    )
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope="module")
def applied_schema(postgres_container, schema_dir):
    """Apply all init scripts via psycopg2 and return a connection URL."""

    # 1. Connect to default 'test' database to run 00 scripts
    conn = psycopg2.connect(_clean_url(postgres_container.get_connection_url()))
    conn.autocommit = True
    cursor = conn.cursor()

    # Order: 00 shell script → 01 schema → 02 roles → hypertables
    # The 00 shell script creates databases and roles via psql meta-commands.
    # We execute the SQL equivalents directly.
    _bootstrap_databases_and_roles(cursor)

    cursor.close()
    conn.close()

    # 2. Connect to dora_metrics to apply the schema, roles, and hypertables
    url = postgres_container.get_connection_url()
    # Replace database name with dora_metrics
    conn2 = psycopg2.connect(_switch_db(url, "dora_metrics"))
    conn2.autocommit = True
    cursor2 = conn2.cursor()

    # Apply 01-dora-schema.sql
    schema_sql = schema_dir / "init" / "01-dora-schema.sql"
    print(f"Applying: {schema_sql.name}...")
    execute_sql_file(cursor2, schema_sql)

    # Apply 02-dora-roles.sql
    roles_sql = schema_dir / "init" / "02-dora-roles.sql"
    print(f"Applying: {roles_sql.name}...")
    execute_sql_file(cursor2, roles_sql)

    # Apply hypertables.sql
    hypertables_sql = schema_dir / "timescaledb" / "hypertables.sql"
    print(f"Applying: {hypertables_sql.name}...")
    execute_sql_file(cursor2, hypertables_sql)

    cursor2.close()
    conn2.close()

    return _switch_db(url, "dora_metrics")


def _bootstrap_databases_and_roles(cursor):
    """Bootstrap equivalent of 00-create-databases.sh."""
    print("Bootstrapping databases and roles (00-create-databases.sh equivalent)...")
    # CREATE DATABASE cannot be run inside a transaction block, so we use
    # direct SQL with exception-safe pattern via separate connection.
    for db in ("dora_metrics", "infisical", "defectdojo"):
        cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (db,)
        )
        if cursor.fetchone() is None:
            # Must run outside transaction — autocommit handles this
            conn = cursor.connection
            old_autocommit = conn.autocommit
            conn.autocommit = True
            # Need a separate cursor for CREATE DATABASE
            cur2 = conn.cursor()
            cur2.execute(f'CREATE DATABASE "{db}"')
            cur2.close()
            conn.autocommit = old_autocommit
            print(f"  Created database: {db}")
        else:
            print(f"  Database already exists: {db}")
    for role in ("dora_app", "infisical_app", "defectdojo_app"):
        cursor.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE "{role}" WITH LOGIN PASSWORD 'change_me_in_production';  -- pragma: allowlist secret
                    RAISE NOTICE 'Created role: {role}';
                ELSE
                    RAISE NOTICE 'Role already exists: {role}';
                END IF;
            END
            $$;
        """)


def _switch_db(url: str, dbname: str) -> str:
    """Replace the database name in a postgres connection URL and strip driver prefix."""
    import urllib.parse
    # Strip '+psycopg2' from scheme if present (testcontainers adds it, psycopg2 can't parse it)
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    parsed = urllib.parse.urlparse(url)
    path = f"/{dbname}"
    return parsed._replace(path=path).geturl()


def _clean_url(url: str) -> str:
    """Strip driver prefix from testcontainers connection URL."""
    return url.replace("postgresql+psycopg2://", "postgresql://")


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestSchema:
    """Validate the full TimescaleDB schema."""

    @pytest.fixture(autouse=True)
    def db_cursor(self, applied_schema):
        """Provide a database cursor for each test."""
        conn = psycopg2.connect(applied_schema)
        conn.autocommit = True
        cursor = conn.cursor()
        yield cursor
        cursor.close()
        conn.close()

    # ── Table existence ───────────────────────────────────────────────────

    @pytest.mark.parametrize("table_name", [
        "event_queue",
        "raw_events",
        "dora_snapshots",
        "archetype_history",
        "wellbeing_surveys",
        "vsi_stage_breakdown",
    ])
    def test_table_exists(self, db_cursor, table_name):
        """AC-02: Verify all 6 tables exist in the dora_metrics database."""
        db_cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = %s
            )
        """, (table_name,))
        exists = db_cursor.fetchone()[0]
        assert exists, f"Table '{table_name}' does not exist"

    # ── Hypertable verification ───────────────────────────────────────────

    @pytest.mark.parametrize("hypertable_name,expected_chunk_interval", [
        ("raw_events", "1 day"),
        ("dora_snapshots", "7 days"),
        ("vsi_stage_breakdown", "1 day"),
    ])
    def test_hypertable_exists(self, db_cursor, hypertable_name, expected_chunk_interval):
        """AC-04: Verify 3 tables are TimescaleDB hypertables with correct chunk intervals."""
        db_cursor.execute("""
            SELECT h.hypertable_name, d.time_interval
            FROM timescaledb_information.hypertables h
            LEFT JOIN timescaledb_information.dimensions d
                ON d.hypertable_name = h.hypertable_name
                AND d.hypertable_schema = h.hypertable_schema
            WHERE h.hypertable_name = %s
              AND h.hypertable_schema = 'public'
        """, (hypertable_name,))
        result = db_cursor.fetchone()
        assert result is not None, f"'{hypertable_name}' is not a hypertable"
        actual_name, actual_interval = result
        assert actual_name == hypertable_name
        assert expected_chunk_interval in str(actual_interval).lower(), \
            f"Expected chunk interval '{expected_chunk_interval}', got '{actual_interval}'"

    # ── Role verification ─────────────────────────────────────────────────

    def test_dora_app_role_exists(self, db_cursor):
        """AC-03: Verify dora_app role exists and is NOT superuser."""
        db_cursor.execute(
            "SELECT rolname, rolsuper FROM pg_roles WHERE rolname = 'dora_app'"
        )
        role = db_cursor.fetchone()
        assert role is not None, "Role 'dora_app' does not exist"
        role_name, is_super = role
        assert not is_super, "dora_app role has superuser privileges — violates least-privilege policy"

    # ── Permission verification ───────────────────────────────────────────

    def test_dora_app_event_queue_insert_only(self, db_cursor):
        """Verify dora_app has INSERT only on event_queue."""
        db_cursor.execute("""
            SELECT privilege_type
            FROM information_schema.table_privileges
            WHERE table_schema = 'public'
              AND table_name = 'event_queue'
              AND grantee = 'dora_app'
            ORDER BY privilege_type
        """)
        grants = [row[0] for row in db_cursor.fetchall()]
        assert grants == ["INSERT"], \
            f"Expected only INSERT on event_queue, got: {grants}"

    def test_dora_app_raw_events_select_insert(self, db_cursor):
        """Verify dora_app has SELECT and INSERT on raw_events."""
        db_cursor.execute("""
            SELECT privilege_type
            FROM information_schema.table_privileges
            WHERE table_schema = 'public'
              AND table_name = 'raw_events'
              AND grantee = 'dora_app'
            ORDER BY privilege_type
        """)
        grants = [row[0] for row in db_cursor.fetchall()]
        assert set(grants) == {"INSERT", "SELECT"}, \
            f"Expected INSERT and SELECT on raw_events, got: {grants}"

    def test_dora_app_dora_snapshots_select_insert(self, db_cursor):
        """Verify dora_app has SELECT and INSERT on dora_snapshots."""
        db_cursor.execute("""
            SELECT privilege_type
            FROM information_schema.table_privileges
            WHERE table_schema = 'public'
              AND table_name = 'dora_snapshots'
              AND grantee = 'dora_app'
            ORDER BY privilege_type
        """)
        grants = [row[0] for row in db_cursor.fetchall()]
        assert set(grants) == {"INSERT", "SELECT"}, \
            f"Expected INSERT and SELECT on dora_snapshots, got: {grants}"

    @pytest.mark.parametrize("table_name", [
        "archetype_history",
        "wellbeing_surveys",
        "vsi_stage_breakdown",
    ])
    def test_dora_app_readonly_tables(self, db_cursor, table_name):
        """Verify dora_app has SELECT only on read-only tables."""
        db_cursor.execute("""
            SELECT privilege_type
            FROM information_schema.table_privileges
            WHERE table_schema = 'public'
              AND table_name = %s
              AND grantee = 'dora_app'
            ORDER BY privilege_type
        """, (table_name,))
        grants = [row[0] for row in db_cursor.fetchall()]
        assert grants == ["SELECT"], \
            f"Expected only SELECT on {table_name}, got: {grants}"

    # ── Idempotency test ──────────────────────────────────────────────────

    def test_init_scripts_idempotent(self, applied_schema, schema_dir):
        """AC-01: Verify all init SQL scripts can be re-run safely."""
        conn = psycopg2.connect(applied_schema)
        conn.autocommit = True
        cursor = conn.cursor()

        # Re-run all SQL scripts in order
        scripts = sorted((schema_dir / "init").glob("*.sql")) + \
                  sorted((schema_dir / "timescaledb").glob("*.sql"))

        for script in scripts:
            print(f"Re-running: {script.name}...")
            execute_sql_file(cursor, script)

        # Verify tables still exist after re-run
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('event_queue', 'raw_events', 'dora_snapshots',
                                 'archetype_history', 'wellbeing_surveys', 'vsi_stage_breakdown')
        """)
        count = cursor.fetchone()[0]
        assert count == 6, f"Expected 6 tables after re-run, found {count}"

        cursor.close()
        conn.close()
