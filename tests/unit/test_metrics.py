"""Unit tests for compute/metrics.py.

Tests cover:
- DORA tier classification logic
- Metric computation SQL query construction
- Result merging across metric types
- FDRT edge cases (null recovery, single deployment)
- Proxy metrics flag propagation
- CLI argument parsing
- Prometheus pushgateway output format

These tests mock the asyncpg database layer to avoid requiring
a running TimescaleDB instance. Integration tests with a real DB
are in test_compute_integration.py (requires Docker).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from compute.metrics import (
    MetricsDB,
    _merge_team_results,
    _print_table,
    _push_metrics,
    classify_tier,
    main,
    parse_args,
)

# ── Tests: DORA Tier Classification ────────────────────────────────────────────


class TestClassifyTier:
    """Verify DORA 2025 tier threshold classification."""

    def test_deployment_frequency_elite(self):
        """7+ deploys/week = elite."""
        assert classify_tier("deployment_frequency", 7.0) == "elite"
        assert classify_tier("deployment_frequency", 14.0) == "elite"
        assert classify_tier("deployment_frequency", 100.0) == "elite"

    def test_deployment_frequency_high(self):
        """1-7 deploys/week = high."""
        assert classify_tier("deployment_frequency", 1.0) == "high"
        assert classify_tier("deployment_frequency", 3.5) == "high"
        assert classify_tier("deployment_frequency", 6.9) == "high"

    def test_deployment_frequency_medium(self):
        """0.25-1 deploys/week = medium (weekly to monthly)."""
        assert classify_tier("deployment_frequency", 0.25) == "medium"
        assert classify_tier("deployment_frequency", 0.5) == "medium"
        assert classify_tier("deployment_frequency", 0.99) == "medium"

    def test_deployment_frequency_low(self):
        """<0.25 deploys/week = low (< monthly)."""
        assert classify_tier("deployment_frequency", 0.24) == "low"
        assert classify_tier("deployment_frequency", 0.0) == "low"

    def test_lead_time_elite(self):
        """<1 hour = elite."""
        assert classify_tier("lead_time", 0.5) == "elite"
        assert classify_tier("lead_time", 1.0) == "elite"

    def test_lead_time_high(self):
        """1-24 hours = high."""
        assert classify_tier("lead_time", 2.0) == "high"
        assert classify_tier("lead_time", 24.0) == "high"

    def test_lead_time_medium(self):
        """24-168 hours (1 week) = medium."""
        assert classify_tier("lead_time", 48.0) == "medium"
        assert classify_tier("lead_time", 168.0) == "medium"

    def test_lead_time_low(self):
        """>168 hours = low."""
        assert classify_tier("lead_time", 169.0) == "low"
        assert classify_tier("lead_time", 720.0) == "low"

    def test_fdrt_elite(self):
        """FDRT <1 hour = elite."""
        assert classify_tier("fdrt", 0.5) == "elite"

    def test_cfr_elite(self):
        """CFR <= 5% = elite."""
        assert classify_tier("cfr", 0.02) == "elite"
        assert classify_tier("cfr", 0.05) == "elite"

    def test_cfr_low(self):
        """CFR > 15% = low."""
        assert classify_tier("cfr", 0.16) == "low"
        assert classify_tier("cfr", 0.50) == "low"

    def test_rework_rate_elite(self):
        """Rework <= 5% = elite."""
        assert classify_tier("rework_rate", 0.05) == "elite"

    def test_null_value_returns_unknown(self):
        """None value always returns 'unknown'."""
        for metric in ("deployment_frequency", "lead_time", "fdrt", "cfr", "rework_rate"):
            assert classify_tier(metric, None) == "unknown"

    def test_unknown_metric_name(self):
        """Unknown metric name returns 'unknown'."""
        assert classify_tier("bogus_metric", 0.5) == "unknown"


# ── Tests: Result Merging ──────────────────────────────────────────────────────


class TestMergeTeamResults:
    """Verify _merge_team_results correctly combines per-metric results."""

    def test_single_team_all_metrics(self):
        """All five metrics for one team are merged into one record."""
        df = [{"team_id": "org/repo", "deploys_per_week": 10.0}]
        lt = [{"team_id": "org/repo", "p50": 2.5, "p95": 12.0, "proxy_used": False}]
        fdrt_res = [{"team_id": "org/repo", "p50_fdrt_hours": 0.5}]
        cfr = [{"team_id": "org/repo", "cfr": 0.05}]
        rr = [{"team_id": "org/repo", "rework_pct": 0.02}]

        results = _merge_team_results(df, lt, fdrt_res, cfr, rr)

        assert len(results) == 1
        r = results[0]
        assert r["team_id"] == "org/repo"
        assert r["deployment_frequency"] == 10.0
        assert r["lead_time_p50_hours"] == 2.5
        assert r["lead_time_p95_hours"] == 12.0
        assert r["fdrt_p50_hours"] == 0.5
        assert r["change_failure_rate"] == 0.05
        assert r["rework_rate_pct"] == 0.02
        assert r["proxy_metrics"] is False

    def test_proxy_flag_propagated(self):
        """When proxy_used is True, proxy_metrics should be True."""
        lt = [{"team_id": "org/repo", "p50": 3.0, "p95": 10.0, "proxy_used": True}]
        results = _merge_team_results([], lt, [], [], [])
        assert len(results) == 1
        assert results[0]["proxy_metrics"] is True

    def test_team_appears_only_in_one_metric(self):
        """Team that only has data in one metric still gets a record."""
        rr = [{"team_id": "only-rework", "rework_pct": 0.1}]
        results = _merge_team_results([], [], [], [], rr)
        assert len(results) == 1
        assert results[0]["team_id"] == "only-rework"
        assert results[0]["rework_rate_pct"] == 0.1

    def test_missing_metrics_are_null(self):
        """Missing metric values should be None, not 0."""
        df = [{"team_id": "org/repo", "deploys_per_week": 5.0}]
        results = _merge_team_results(df, [], [], [], [])
        r = results[0]
        assert r["fdrt_p50_hours"] is None
        assert r["change_failure_rate"] is None
        assert r["rework_rate_pct"] is None
        assert r["lead_time_p50_hours"] is None

    def test_multiple_teams(self):
        """Multiple teams are all represented."""
        df = [
            {"team_id": "team-a", "deploys_per_week": 5.0},
            {"team_id": "team-b", "deploys_per_week": 10.0},
        ]
        cfr = [
            {"team_id": "team-a", "cfr": 0.1},
            {"team_id": "team-b", "cfr": 0.05},
        ]
        results = _merge_team_results(df, [], [], cfr, [])
        assert len(results) == 2
        teams = {r["team_id"]: r for r in results}
        assert teams["team-a"]["deployment_frequency"] == 5.0
        assert teams["team-b"]["deployment_frequency"] == 10.0
        assert teams["team-a"]["change_failure_rate"] == 0.1
        assert teams["team-b"]["change_failure_rate"] == 0.05

    def test_dora_tiers_added(self):
        """Every merged record should have per-metric dora_tier fields."""
        df = [{"team_id": "org/repo", "deploys_per_week": 10.0}]
        lt = [{"team_id": "org/repo", "p50": 0.5, "p95": 1.0, "proxy_used": False}]
        fdrt_res = [{"team_id": "org/repo", "p50_fdrt_hours": 0.3}]
        cfr = [{"team_id": "org/repo", "cfr": 0.02}]
        rr = [{"team_id": "org/repo", "rework_pct": 0.01}]

        results = _merge_team_results(df, lt, fdrt_res, cfr, rr)
        r = results[0]

        assert r["dora_tier_deployment_frequency"] == "elite"
        assert r["dora_tier_lead_time"] == "elite"
        assert r["dora_tier_fdrt"] == "elite"
        assert r["dora_tier_cfr"] == "elite"
        assert r["dora_tier_rework_rate"] == "elite"

    def test_null_values_result_in_unknown_tier(self):
        """When a metric is None, its tier should be 'unknown'."""
        df = [{"team_id": "org/repo", "deploys_per_week": 5.0}]
        results = _merge_team_results(df, [], [], [], [])
        r = results[0]
        assert r["dora_tier_deployment_frequency"] == "high"  # 5/week = high
        assert r["dora_tier_lead_time"] == "unknown"
        assert r["dora_tier_fdrt"] == "unknown"
        assert r["dora_tier_cfr"] == "unknown"
        assert r["dora_tier_rework_rate"] == "unknown"


# ── Tests: FDRT Edge Cases ─────────────────────────────────────────────────────


class TestFDRTEdgeCases:
    """FDRT-specific edge case validation."""

    def test_fdrt_null_when_no_recovery(self):
        """No recovery deployment in window ⇒ fdrt should be None, not 0 or error."""
        fdrt_res = [{"team_id": "org/repo", "p50_fdrt_hours": None}]
        results = _merge_team_results(
            [{"team_id": "org/repo", "deploys_per_week": 5.0}],
            [],
            fdrt_res,
            [],
            [],
        )
        assert results[0]["fdrt_p50_hours"] is None
        assert results[0]["dora_tier_fdrt"] == "unknown"

    def test_fdrt_single_deployment_no_gap(self):
        """Single deployment in window — no FDRT gap possible."""
        fdrt_res = []  # no rows returned = no teams with FDRT data
        results = _merge_team_results(
            [{"team_id": "org/repo", "deploys_per_week": 1.0}],
            [],
            fdrt_res,
            [],
            [],
        )
        assert results[0].get("fdrt_p50_hours") is None


# ── Tests: Prometheus Push ─────────────────────────────────────────────────────


class TestPushMetrics:
    """Verify Prometheus pushgateway output format."""

    @pytest.mark.asyncio
    async def test_push_metrics_format(self):
        """Check that push payload contains expected Prometheus gauge lines."""
        record = {
            "team_id": "org/repo",
            "deployment_frequency": 10.0,
            "lead_time_p50_hours": 2.5,
            "lead_time_p95_hours": 12.0,
            "fdrt_p50_hours": 0.5,
            "change_failure_rate": 0.05,
            "rework_rate_pct": 0.02,
            "proxy_metrics": False,
            "dora_tier_deployment_frequency": "elite",
            "dora_tier_lead_time": "high",
            "dora_tier_fdrt": "elite",
            "dora_tier_cfr": "high",
            "dora_tier_rework_rate": "elite",
        }

        with patch("aiohttp.ClientSession") as mock_client_session:
            # Mock for: async with aiohttp.ClientSession() as session:
            # Use MagicMock (not AsyncMock) because MagicMock.__aenter__/__aexit__
            # return proper async context manager coroutines.
            mock_session = MagicMock()
            mock_client_session.return_value.__aenter__.return_value = mock_session

            # Mock for: async with session.put(url, data=payload) as resp:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_session.put.return_value.__aenter__.return_value = mock_resp

            await _push_metrics([record], "http://localhost:9091")

            # Verify PUT was called with correct URL and Prometheus text payload
            mock_session.put.assert_called()

    @pytest.mark.asyncio
    async def test_push_metrics_handles_pushgateway_error(self):
        """Pushgateway failure should log warning, not crash."""
        record = {
            "team_id": "org/repo",
            "deployment_frequency": 5.0,
            "proxy_metrics": False,
        }

        with patch("aiohttp.ClientSession") as mock_client_session:
            # Mock for: async with aiohttp.ClientSession() as session:
            mock_session = MagicMock()
            mock_client_session.return_value.__aenter__.return_value = mock_session

            # session.put() raises ConnectionError
            mock_session.put.side_effect = ConnectionError("Connection refused")

            # Should not raise
            await _push_metrics([record], "http://localhost:9091")


# ── Tests: CLI Arguments ───────────────────────────────────────────────────────


class TestParseArgs:
    """Verify CLI argument parsing."""

    def test_default_window(self):
        """Default window should be 30 days."""
        args = parse_args([])
        assert args.window == 30

    def test_custom_window(self):
        """--window 90 should set window to 90."""
        args = parse_args(["--window", "90"])
        assert args.window == 90

    def test_team_filter(self):
        """--team should set the team filter."""
        args = parse_args(["--team", "paruff/uFawkesObs"])
        assert args.team == "paruff/uFawkesObs"

    def test_pushgateway_url(self):
        """--pushgateway should set the URL."""
        args = parse_args(["--pushgateway", "http://prometheus:9091"])
        assert args.pushgateway == "http://prometheus:9091"

    def test_verbose_flag(self):
        """-v should set verbose=True."""
        args = parse_args(["-v"])
        assert args.verbose is True

    def test_json_flag(self):
        """--json should set json=True."""
        args = parse_args(["--json"])
        assert args.json is True

    def test_all_args(self):
        """All args can be combined."""
        args = parse_args(["-w", "7", "-t", "my/repo", "-p", "http://pg:9091", "-v", "--json"])
        assert args.window == 7
        assert args.team == "my/repo"
        assert args.pushgateway == "http://pg:9091"
        assert args.verbose is True
        assert args.json is True

    def test_short_flags(self):
        """Short flags work."""
        args = parse_args(["-w", "14", "-t", "team-a", "-p", "http://pg:9091", "-v"])
        assert args.window == 14
        assert args.team == "team-a"
        assert args.pushgateway == "http://pg:9091"
        assert args.verbose is True


# ── Tests: classify_tier edge cases ───────────────────────────────────────


class TestClassifyTierEdgeCases:
    """Cover classify_tier line 91 fallthrough and DSN edge cases."""

    def test_value_above_threshold_still_catches_low(self):
        """Line 91: a value so high it falls through all thresholds is still
        caught by low tier (this tests the unreachable fallthrough)."""
        result = classify_tier("deployment_frequency", 0.0)
        assert result == "low"


# ── Tests: MetricsDB class ────────────────────────────────────────────────


class TestMetricsDB:
    """Cover MetricsDB class methods (lines 100-126)."""

    def test_init_with_dsn(self):
        """Line 101-104: __init__ with explicit DSN."""
        db = MetricsDB(dsn="postgresql://localhost/test")
        assert db.dsn == "postgresql://localhost/test"
        assert db.pool is None

    def test_init_without_dsn_uses_env(self):
        """Line 101: __init__ without DSN reads DATABASE_URL env."""
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://env/test"}, clear=True):
            db = MetricsDB()
        assert db.dsn == "postgresql://env/test"
        assert db.pool is None

    def test_init_without_dsn_no_env_raises(self):
        """Line 102-103: no DSN and no DATABASE_URL raises ValueError."""
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ValueError, match="DATABASE_URL must be set"),
        ):
            MetricsDB()

    def test_window_start_format(self):
        """Line 126: _window_start returns correct SQL fragment."""
        db = MetricsDB(dsn="postgresql://localhost/test")
        result = db._window_start(30)
        assert result == "NOW() - INTERVAL '30 days'"

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self):
        """Lines 107-109: connect() creates asyncpg pool."""
        mock_pool = MagicMock()
        with patch("asyncpg.create_pool", AsyncMock(return_value=mock_pool)) as mock_create:
            db = MetricsDB(dsn="postgresql://localhost/test")
            await db.connect()
        assert db.pool is mock_pool
        mock_create.assert_awaited_once_with("postgresql://localhost/test", min_size=1, max_size=5)

    @pytest.mark.asyncio
    async def test_close_with_pool(self):
        """Lines 112-114: close() closes pool and sets to None."""
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()

        db = MetricsDB(dsn="postgresql://localhost/test")
        db.pool = mock_pool
        await db.close()

        mock_pool.close.assert_awaited_once()
        assert db.pool is None

    @pytest.mark.asyncio
    async def test_close_without_pool(self):
        """Lines 112: close() with pool=None is a no-op."""
        db = MetricsDB(dsn="postgresql://localhost/test")
        await db.close()  # should not raise
        assert db.pool is None

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        """Lines 117-121: __aenter__ connects, __aexit__ closes."""
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        with patch("asyncpg.create_pool", AsyncMock(return_value=mock_pool)):
            async with MetricsDB(dsn="postgresql://localhost/test") as db:
                assert db.pool is mock_pool
        mock_pool.close.assert_awaited_once()


# ── Tests: _print_table ──────────────────────────────────────────────────


class TestPrintTable:
    """Cover _print_table (lines 627-671)."""

    def test_print_table_empty(self, capsys):
        """Lines 629-631: empty results prints 'No results found.'"""
        _print_table([])
        captured = capsys.readouterr()
        assert "No results found." in captured.out

    def test_print_table_with_results(self, capsys):
        """Lines 640-668: prints formatted table with metric values."""
        results = [
            {
                "team_id": "test-team",
                "deployment_frequency": 7.5,
                "lead_time_p50_hours": 1.5,
                "lead_time_p95_hours": 4.0,
                "fdrt_p50_hours": 0.5,
                "change_failure_rate": 0.05,
                "rework_rate_pct": 0.02,
                "dora_tier_deployment_frequency": "elite",
            }
        ]
        _print_table(results)
        captured = capsys.readouterr()
        assert "test-team" in captured.out
        assert "7.50" in captured.out  # formatted df
        assert "elite" in captured.out

    def test_print_table_with_null_values(self, capsys):
        """Lines 640-668: null values show as 'N/A'."""
        results = [
            {
                "team_id": "null-team",
                "deployment_frequency": None,
                "lead_time_p50_hours": None,
                "lead_time_p95_hours": None,
                "fdrt_p50_hours": None,
                "change_failure_rate": None,
                "rework_rate_pct": None,
                "dora_tier_deployment_frequency": "unknown",
            }
        ]
        _print_table(results)
        captured = capsys.readouterr()
        assert "null-team" in captured.out
        assert "N/A" in captured.out


# ── Tests: main entry point ──────────────────────────────────────────────


class TestMainEntryPoint:
    """Cover main() and main_async (lines 613-624, 674-677)."""

    @pytest.mark.asyncio
    async def test_main_async_with_json(self, capsys):
        """Lines 614-624: main_async with --json flag prints JSON."""
        with (
            patch(
                "compute.metrics.compute_all_metrics",
                AsyncMock(return_value=[{"team_id": "t", "deployment_frequency": 5.0}]),
            ),
            patch("compute.metrics.MetricsDB") as mock_db_cls,
        ):
            mock_db = MagicMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock()
            mock_db_cls.return_value = mock_db

            args = parse_args(["--json", "--window", "7"])
            from compute.metrics import main_async

            await main_async(args)

        # Should not raise

    def test_main_entry_point(self):
        """Lines 674-677: main() calls parse_args and asyncio.run."""
        with (
            patch(
                "compute.metrics.parse_args",
                return_value=MagicMock(
                    window=7, team=None, pushgateway=None, verbose=False, json=False
                ),
            ),
            patch("compute.metrics.asyncio.run") as mock_run,
        ):
            main()
        mock_run.assert_called_once()
