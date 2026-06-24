"""Integration tests for compute/metrics.py against a real TimescaleDB.

Spins up a TimescaleDB container via testcontainers, applies all init scripts
and migration 003, inserts fixture deployment data, and verifies that all five
DORA metrics are computed correctly.

Requires: Docker daemon running.
"""

from pathlib import Path

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer

from compute.metrics import compute_all_metrics, parse_args

# ── Fixture data ───────────────────────────────────────────────────────────────

FIXTURE_TEAM = "test-org/test-service"

FIXTURE_SQL = f"""
-- Fixture: successful deployments (for Deployment Frequency, Lead Time, FDRT)
INSERT INTO raw_events (event_type, source, outcome, metadata, recorded_at) VALUES
    ('deployment', '{FIXTURE_TEAM}', 'success', '{{"commit_sha": "abc1", "first_commit_at": "2026-06-01T08:00:00Z", "deployed_at": "2026-06-01T10:00:00Z"}}'::jsonb, '2026-06-01T10:00:00Z'),
    ('deployment', '{FIXTURE_TEAM}', 'success', '{{"commit_sha": "abc2", "first_commit_at": "2026-06-03T08:00:00Z", "deployed_at": "2026-06-03T12:00:00Z"}}'::jsonb, '2026-06-03T12:00:00Z'),
    ('deployment', '{FIXTURE_TEAM}', 'success', '{{"commit_sha": "abc3", "first_commit_at": "2026-06-05T08:00:00Z", "deployed_at": "2026-06-05T09:30:00Z"}}'::jsonb, '2026-06-05T09:30:00Z'),
    ('deployment', '{FIXTURE_TEAM}', 'success', '{{"commit_sha": "abc4", "first_commit_at": "2026-06-07T08:00:00Z", "deployed_at": "2026-06-07T11:00:00Z"}}'::jsonb, '2026-06-07T11:00:00Z'),
    ('deployment', '{FIXTURE_TEAM}', 'success', '{{"commit_sha": "abc5", "first_commit_at": "2026-06-10T08:00:00Z", "deployed_at": "2026-06-10T14:00:00Z"}}'::jsonb, '2026-06-10T14:00:00Z'),
    ('deployment', '{FIXTURE_TEAM}', 'success', '{{"commit_sha": "abc6", "first_commit_at": "2026-06-12T08:00:00Z", "deployed_at": "2026-06-12T10:00:00Z"}}'::jsonb, '2026-06-12T10:00:00Z'),
    ('deployment', '{FIXTURE_TEAM}', 'success', '{{"commit_sha": "abc7", "first_commit_at": "2026-06-14T08:00:00Z", "deployed_at": "2026-06-14T16:00:00Z"}}'::jsonb, '2026-06-14T16:00:00Z'),
    ('deployment', '{FIXTURE_TEAM}', 'success', '{{"commit_sha": "abc8", "first_commit_at": "2026-06-16T08:00:00Z", "deployed_at": "2026-06-16T10:30:00Z"}}'::jsonb, '2026-06-16T10:30:00Z');

-- Fixture: failed deployment followed by successful recovery (for FDRT)
INSERT INTO raw_events (event_type, source, outcome, metadata, recorded_at) VALUES
    ('deployment', '{FIXTURE_TEAM}', 'failure', '{{"commit_sha": "fail1", "first_commit_at": "2026-06-18T08:00:00Z", "deployed_at": "2026-06-18T10:00:00Z"}}'::jsonb, '2026-06-18T10:00:00Z'),
    ('deployment', '{FIXTURE_TEAM}', 'success', '{{"commit_sha": "recovery1", "first_commit_at": "2026-06-18T10:30:00Z", "deployed_at": "2026-06-18T11:00:00Z"}}'::jsonb, '2026-06-18T11:00:00Z');

-- Fixture: rollback followed by successful recovery (for FDRT)
INSERT INTO raw_events (event_type, source, outcome, metadata, recorded_at) VALUES
    ('deployment', '{FIXTURE_TEAM}', 'rollback', '{{"commit_sha": "roll1", "first_commit_at": "2026-06-20T08:00:00Z", "deployed_at": "2026-06-20T10:00:00Z"}}'::jsonb, '2026-06-20T10:00:00Z'),
    ('deployment', '{FIXTURE_TEAM}', 'success', '{{"commit_sha": "recovery2", "first_commit_at": "2026-06-20T12:00:00Z", "deployed_at": "2026-06-20T14:00:00Z"}}'::jsonb, '2026-06-20T14:00:00Z');

-- Fixture: user-visible rework events (for Rework Rate)
INSERT INTO raw_events (event_type, source, outcome, metadata, recorded_at) VALUES
    ('rework', '{FIXTURE_TEAM}', 'success', '{{"deployment_sha": "abc5", "user_visible": true, "rework_type": "hotfix"}}'::jsonb, '2026-06-11T08:00:00Z');

-- Fixture: non-user-visible rework (should NOT be counted in rework rate)
INSERT INTO raw_events (event_type, source, outcome, metadata, recorded_at) VALUES
    ('rework', '{FIXTURE_TEAM}', 'success', '{{"deployment_sha": "abc6", "user_visible": false, "rework_type": "internal"}}'::jsonb, '2026-06-13T08:00:00Z');

-- Fixture: another team (to test multi-team aggregation)
INSERT INTO raw_events (event_type, source, outcome, metadata, recorded_at) VALUES
    ('deployment', 'other-team/other-service', 'success', '{{"commit_sha": "x1", "first_commit_at": "2026-06-01T08:00:00Z", "deployed_at": "2026-06-01T09:00:00Z"}}'::jsonb, '2026-06-01T09:00:00Z');
"""


# ── Helpers ────────────────────────────────────────────────────────────────────


def find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    while current.name != "ufawkesdora" and current.parent != current:
        current = current.parent
    return current


def execute_sql_file(cursor, filepath: Path):
    """Read and execute a SQL file via psycopg2."""
    from tests.unit.test_schema import execute_sql_file as _execute

    _execute(cursor, filepath)


def split_sql_statements(sql: str) -> list[str]:
    from tests.unit.test_schema import split_sql_statements as _split

    return _split(sql)


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def schema_dir() -> Path:
    return find_repo_root() / "database"


@pytest.fixture(scope="module")
def postgres_container() -> PostgresContainer:
    container = PostgresContainer(
        image="timescale/timescaledb:latest-pg16",
        driver="psycopg2",
    )
    container.start()
    yield container
    container.stop()


def _clean_url(url: str) -> str:
    return url.replace("postgresql+psycopg2://", "postgresql://")


def _switch_db(url: str, dbname: str) -> str:
    import urllib.parse

    url = url.replace("postgresql+psycopg2://", "postgresql://")
    parsed = urllib.parse.urlparse(url)
    return parsed._replace(path=f"/{dbname}").geturl()


@pytest.fixture(scope="module")
def db_url(postgres_container, schema_dir) -> str:
    """Apply init scripts, migrations, and fixture data. Return connection URL."""
    from tests.unit.test_schema import _bootstrap_databases_and_roles

    # 1. Bootstrap databases and roles
    conn = psycopg2.connect(_clean_url(postgres_container.get_connection_url()))
    conn.autocommit = True
    cursor = conn.cursor()
    _bootstrap_databases_and_roles(cursor)
    cursor.close()
    conn.close()

    # 2. Connect to dora_metrics and apply schema
    url = _switch_db(postgres_container.get_connection_url(), "dora_metrics")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cursor = conn.cursor()

    # Apply init scripts in order
    for script in [
        schema_dir / "init" / "01-dora-schema.sql",
        schema_dir / "init" / "02-dora-roles.sql",
        schema_dir / "timescaledb" / "hypertables.sql",
    ]:
        print(f"Applying: {script.name}...")
        execute_sql_file(cursor, script)

    # Apply migration 001 first (creates _schema_migrations table that later
    # migrations reference). Uses IF NOT EXISTS throughout, so safe to apply
    # on top of the init scripts.
    for mig_name in ["001-initial-schema.sql", "003-extend-dora-snapshots.sql"]:
        mig_path = schema_dir / "migrations" / mig_name
        print(f"Applying: {mig_path.name}...")
        content = mig_path.read_text()
        statements = split_sql_statements(content)
        for stmt in statements:
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                cursor.execute(stmt)
            except Exception as e:
                raise RuntimeError(f"Error in {mig_name}:\n{stmt[:200]}\nError: {e}") from e

    # Insert fixture data
    print("Inserting fixture data...")
    for stmt in split_sql_statements(FIXTURE_SQL):
        stmt = stmt.strip()
        if stmt:
            cursor.execute(stmt)

    cursor.close()
    conn.close()

    return url


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestMetricsIntegration:
    """Integration tests: run compute against real TimescaleDB with fixture data."""

    @pytest.mark.asyncio
    async def test_all_five_metrics_computed(self, db_url):
        """Verify all five DORA metrics are computed from fixture data."""
        # Override DB connection to use the test container
        import os

        os.environ["DATABASE_URL"] = db_url

        parse_args(["--window", "30", "--team", FIXTURE_TEAM, "--json"])
        results = await compute_all_metrics(
            window_days=30,
            team=FIXTURE_TEAM,
        )

        assert len(results) >= 1, "Expected at least one team result"
        team_result = None
        for r in results:
            if r["team_id"] == FIXTURE_TEAM:
                team_result = r
                break
        assert team_result is not None, f"Team {FIXTURE_TEAM} not found in results"

        # Deployment Frequency: 10 successful deploys in 30d = ~2.33/week
        df = team_result["deployment_frequency"]
        assert df is not None and df > 0, f"Expected positive DF, got {df}"
        assert 2.0 <= df <= 3.0, f"DF {df} not in expected range (2.0-3.0)"

        # Lead Time: most deploys have 1-4h lead time
        lt_p50 = team_result["lead_time_p50_hours"]
        assert lt_p50 is not None, "lead_time_p50_hours should not be None"
        assert 1.5 <= lt_p50 <= 3.0, f"LT P50 {lt_p50} not in expected range (1.5-3.0)"

        # FDRT: failed deploy at 10:00, recovery at 11:00 = 1h; rollback at 10:00, recovery at 14:00 = 4h
        # P50 of [1.0, 4.0] = 2.5h
        fdrt = team_result["fdrt_p50_hours"]
        assert fdrt is not None, "fdrt_p50_hours should not be None"
        assert 2.0 <= fdrt <= 3.5, f"FDRT {fdrt} not in expected range (2.0-3.5)"

        # Change Failure Rate: 2 failures (1 failure + 1 rollback) / 12 deploys = 0.1667
        cfr = team_result["change_failure_rate"]
        assert cfr is not None, "change_failure_rate should not be None"
        assert 0.10 <= cfr <= 0.20, f"CFR {cfr} not in expected range (0.10-0.20)"

        # Rework Rate: 1 user-visible rework / 12 deploys = 0.0833
        rr = team_result["rework_rate_pct"]
        assert rr is not None, "rework_rate_pct should not be None"
        assert 0.05 <= rr <= 0.10, f"Rework rate {rr} not in expected range (0.05-0.10)"

    @pytest.mark.asyncio
    async def test_dora_tier_classification(self, db_url):
        """Verify DORA tier classification matches expected thresholds."""
        import os

        os.environ["DATABASE_URL"] = db_url

        results = await compute_all_metrics(
            window_days=30,
            team=FIXTURE_TEAM,
        )

        team_result = next(r for r in results if r["team_id"] == FIXTURE_TEAM)

        # DF ~2.33/week = high (1-7)
        assert team_result["dora_tier_deployment_frequency"] in ("high", "elite")

        # FDRT ~2.5h = medium (1-24h range)
        assert team_result["dora_tier_fdrt"] in ("high", "medium")

        # CFR ~16.7% = low (>15%)
        assert team_result["dora_tier_cfr"] == "low"

        # Rework Rate ~8.3% = high (5-10%)
        assert team_result["dora_tier_rework_rate"] == "high"

    @pytest.mark.asyncio
    async def test_dora_snapshots_written(self, db_url):
        """Verify computed results are written to dora_snapshots table."""
        import os

        os.environ["DATABASE_URL"] = db_url

        results = await compute_all_metrics(
            window_days=30,
            team=FIXTURE_TEAM,
        )

        assert len(results) >= 1

        # Verify via direct DB query
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM dora_snapshots WHERE team_id = %s",
            (FIXTURE_TEAM,),
        )
        count = cursor.fetchone()[0]
        assert count >= 1, f"Expected at least 1 snapshot for {FIXTURE_TEAM}, found {count}"

        # Verify new columns are populated
        cursor.execute(
            """SELECT deployment_frequency, fdrt_hours, rework_rate_pct, proxy_metrics, dora_tier
               FROM dora_snapshots WHERE team_id = %s ORDER BY recorded_at DESC LIMIT 1""",
            (FIXTURE_TEAM,),
        )
        row = cursor.fetchone()
        assert row is not None
        df, fdrt, rr, proxy, tier = row
        assert df is not None and df > 0
        assert fdrt is not None
        assert rr is not None
        assert proxy is not None
        assert tier is not None

        cursor.close()
        conn.close()

    @pytest.mark.asyncio
    async def test_multiple_teams(self, db_url):
        """Verify both teams appear in results."""
        import os

        os.environ["DATABASE_URL"] = db_url

        results = await compute_all_metrics(window_days=30)
        team_ids = {r["team_id"] for r in results}
        assert FIXTURE_TEAM in team_ids, f"{FIXTURE_TEAM} not in results"
        assert "other-team/other-service" in team_ids, "other-team/other-service not in results"

    @pytest.mark.asyncio
    async def test_proxy_metrics_flag_false(self, db_url):
        """When first_commit_at is available, proxy_metrics should be False."""
        import os

        os.environ["DATABASE_URL"] = db_url

        results = await compute_all_metrics(
            window_days=30,
            team=FIXTURE_TEAM,
        )
        team_result = next(r for r in results if r["team_id"] == FIXTURE_TEAM)
        # All fixture data has first_commit_at set
        assert team_result.get("proxy_metrics") is False
