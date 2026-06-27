"""Unit tests for compute/vsi.py.

Tests cover:
- PR stage duration computation (coding, review, deploy)
- Deployment linking (nearest deploy after PR merge)
- VSM aggregate metric calculation
- Bottleneck identification
- CI stage handling (null for v0.1)
- Format utilities
- CLI argument parsing
- VSIDB query construction (mocked)

These tests mock the asyncpg database layer to avoid requiring
a running TimescaleDB instance.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from compute.vsi import (
    VSIDB,
    compute_deployment_id,
    compute_pr_stages,
    compute_vsm_metrics,
    format_duration,
    parse_args,
    print_vsm_table,
)

# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_prs():
    """Generate sample merged PR event data."""
    base = datetime(2026, 6, 1, tzinfo=UTC)
    return [
        {
            "repo": "paruff/test-repo",
            "pr_number": 42,
            "first_commit_at": base,
            "opened_at": base + timedelta(hours=2),
            "merged_at": base + timedelta(hours=24),
            "commit_sha": "a" * 40,
        },
        {
            "repo": "paruff/test-repo",
            "pr_number": 43,
            "first_commit_at": base + timedelta(hours=48),
            "opened_at": base + timedelta(hours=50),
            "merged_at": base + timedelta(hours=72),
            "commit_sha": "b" * 40,
        },
    ]


@pytest.fixture
def sample_deployments():
    """Generate sample deployment event data."""
    base = datetime(2026, 6, 1, tzinfo=UTC)
    return [
        {
            "repo": "paruff/test-repo",
            "commit_sha": "a" * 40,
            "deployed_at": base + timedelta(hours=26),
        },
        {
            "repo": "paruff/test-repo",
            "commit_sha": "b" * 40,
            "deployed_at": base + timedelta(hours=74),
        },
    ]


@pytest.fixture
def prs_without_opened():
    """PRs missing opened_at (should be skipped)."""
    base = datetime(2026, 6, 1, tzinfo=UTC)
    return [
        {
            "repo": "paruff/test-repo",
            "pr_number": 99,
            "first_commit_at": base,
            "opened_at": None,
            "merged_at": base + timedelta(hours=24),
            "commit_sha": "c" * 40,
        },
    ]


# ── Tests: compute_deployment_id ───────────────────────────────────────────────


class TestComputeDeploymentId:
    def test_generates_correct_id(self):
        """AC: deployment_id combines repo and PR number."""
        assert compute_deployment_id("paruff/test-repo", 42) == "paruff/test-repo/PR#42"


# ── Tests: compute_pr_stages ───────────────────────────────────────────────────


class TestComputePRStages:
    """Verify stage duration computation from PR and deployment data."""

    def test_coding_stage_correct(self, sample_prs, sample_deployments):
        """AC-01: Coding time = opened_at - first_commit_at."""
        records = compute_pr_stages(sample_prs, sample_deployments)
        coding_records = [r for r in records if r["stage_name"] == "coding"]
        assert len(coding_records) == 2

        # PR #42: coding = 2 hours
        pr42_coding = next(r for r in coding_records if "PR#42" in r["deployment_id"])
        assert pr42_coding["duration_seconds"] == 7200  # 2 hours

        # PR #43: coding = 2 hours
        pr43_coding = next(r for r in coding_records if "PR#43" in r["deployment_id"])
        assert pr43_coding["duration_seconds"] == 7200  # 2 hours

    def test_review_stage_correct(self, sample_prs, sample_deployments):
        """AC-01: Review time = merged_at - opened_at."""
        records = compute_pr_stages(sample_prs, sample_deployments)
        review_records = [r for r in records if r["stage_name"] == "review"]
        assert len(review_records) == 2

        # PR #42: review = 22 hours
        pr42_review = next(r for r in review_records if "PR#42" in r["deployment_id"])
        assert pr42_review["duration_seconds"] == 79200  # 22 hours

    def test_deploy_stage_links_nearest_deployment(self, sample_prs, sample_deployments):
        """AC-01: Deploy time = deployed_at - merged_at (nearest deploy after merge)."""
        records = compute_pr_stages(sample_prs, sample_deployments)
        deploy_records = [r for r in records if r["stage_name"] == "deploy"]
        assert len(deploy_records) == 2

        # PR #42: merged at 24h, deployed at 26h → deploy = 2 hours
        pr42_deploy = next(r for r in deploy_records if "PR#42" in r["deployment_id"])
        assert pr42_deploy["duration_seconds"] == 7200  # 2 hours
        assert pr42_deploy["status"] == "success"

    def test_deploy_pending_when_no_deployment(self, sample_prs):
        """AC: Deploy stage is 'pending' when no deployment found after merge."""
        records = compute_pr_stages(sample_prs, [])
        deploy_records = [r for r in records if r["stage_name"] == "deploy"]
        assert len(deploy_records) == 2
        for dep in deploy_records:
            assert dep["status"] == "pending"
            assert dep["duration_seconds"] == 0

    def test_ci_stage_skipped(self, sample_prs, sample_deployments):
        """AC-01: CI stage is skipped for v0.1 (no CI event schema)."""
        records = compute_pr_stages(sample_prs, sample_deployments)
        ci_records = [r for r in records if r["stage_name"] == "ci"]
        assert len(ci_records) == 2
        for ci in ci_records:
            assert ci["status"] == "skipped"
            assert ci["duration_seconds"] == 0
            assert "CI stage requires CI event schema" in ci["metadata"]["note"]

    def test_skip_pr_without_opened_at(self, prs_without_opened, sample_deployments):
        """AC: PRs without opened_at or first_commit_at are skipped."""
        records = compute_pr_stages(prs_without_opened, sample_deployments)
        # Since opened_at is None, the PR is skipped entirely (no stages computed)
        all_99 = [r for r in records if "PR#99" in r["deployment_id"]]
        assert len(all_99) == 0

    def test_multiple_deployments_same_repo(self):
        """AC: Handles multiple deployments in the same repo correctly."""
        base = datetime(2026, 6, 1, tzinfo=UTC)
        prs = [
            {
                "repo": "paruff/test-repo",
                "pr_number": 1,
                "first_commit_at": base,
                "opened_at": base + timedelta(hours=1),
                "merged_at": base + timedelta(hours=10),
                "commit_sha": "d" * 40,
            },
            {
                "repo": "paruff/test-repo",
                "pr_number": 2,
                "first_commit_at": base + timedelta(hours=12),
                "opened_at": base + timedelta(hours=13),
                "merged_at": base + timedelta(hours=20),
                "commit_sha": "e" * 40,
            },
        ]
        deployments = [
            {
                "repo": "paruff/test-repo",
                "commit_sha": "d" * 40,
                "deployed_at": base + timedelta(hours=11),
            },
            {
                "repo": "paruff/test-repo",
                "commit_sha": "e" * 40,
                "deployed_at": base + timedelta(hours=22),
            },
        ]

        records = compute_pr_stages(prs, deployments)
        pr1_deploy = next(
            r for r in records if r["stage_name"] == "deploy" and "PR#1" in r["deployment_id"]
        )
        assert pr1_deploy["duration_seconds"] == 3600  # 1 hour

        pr2_deploy = next(
            r for r in records if r["stage_name"] == "deploy" and "PR#2" in r["deployment_id"]
        )
        assert pr2_deploy["duration_seconds"] == 7200  # 2 hours


# ── Tests: compute_vsm_metrics ─────────────────────────────────────────────────


class TestComputeVSMMetrics:
    """Verify VSM aggregate metrics computation."""

    def test_vsm_efficiency_calculation(self):
        """AC-02: VSM efficiency = value-add / total * 100."""
        records = [
            {
                "deployment_id": "test/PR#1",
                "stage_name": "coding",
                "duration_seconds": 7200,  # 2h value-add
            },
            {
                "deployment_id": "test/PR#1",
                "stage_name": "review",
                "duration_seconds": 3600,  # 1h wait
            },
            {
                "deployment_id": "test/PR#1",
                "stage_name": "deploy",
                "duration_seconds": 1800,  # 0.5h value-add
            },
            {
                "deployment_id": "test/PR#1",
                "stage_name": "ci",
                "duration_seconds": 0,
            },
        ]

        metrics = compute_vsm_metrics(records)
        assert metrics["total_journeys"] == 1

        journey = metrics["per_deployment"][0]
        assert journey["value_add_seconds"] == 9000  # 7200 + 1800
        assert journey["wait_seconds"] == 3600
        assert journey["total_seconds"] == 12600
        assert journey["vsm_efficiency_pct"] == 71.4  # 9000/12600*100 ≈ 71.4

    def test_bottleneck_identification(self):
        """AC-04: Bottleneck is the stage with highest median duration."""
        records = [
            {"deployment_id": "test/PR#1", "stage_name": "coding", "duration_seconds": 7200},
            {
                "deployment_id": "test/PR#1",
                "stage_name": "review",
                "duration_seconds": 86400,
            },  # 24h
            {"deployment_id": "test/PR#1", "stage_name": "deploy", "duration_seconds": 1800},
            {"deployment_id": "test/PR#1", "stage_name": "ci", "duration_seconds": 0},
            {"deployment_id": "test/PR#2", "stage_name": "coding", "duration_seconds": 3600},
            {
                "deployment_id": "test/PR#2",
                "stage_name": "review",
                "duration_seconds": 43200,
            },  # 12h
            {"deployment_id": "test/PR#2", "stage_name": "deploy", "duration_seconds": 900},
            {"deployment_id": "test/PR#2", "stage_name": "ci", "duration_seconds": 0},
        ]

        metrics = compute_vsm_metrics(records)
        assert metrics["primary_bottleneck"] == "review"

    def test_value_add_wait_breakdown(self):
        """AC-02: Value-add = coding + deploy, Wait = review."""
        records = [
            {"deployment_id": "test/PR#1", "stage_name": "coding", "duration_seconds": 7200},
            {"deployment_id": "test/PR#1", "stage_name": "review", "duration_seconds": 3600},
            {"deployment_id": "test/PR#1", "stage_name": "deploy", "duration_seconds": 1800},
            {"deployment_id": "test/PR#1", "stage_name": "ci", "duration_seconds": 0},
        ]

        metrics = compute_vsm_metrics(records)
        assert metrics["overall_value_add_seconds"] == 9000
        assert metrics["overall_wait_seconds"] == 3600

    def test_bottleneck_prefers_nonzero_stages(self):
        """AC: Bottleneck ignores skipped/zero-duration stages."""
        records = [
            {"deployment_id": "test/PR#1", "stage_name": "coding", "duration_seconds": 3600},
            {"deployment_id": "test/PR#1", "stage_name": "review", "duration_seconds": 7200},
            {"deployment_id": "test/PR#1", "stage_name": "deploy", "duration_seconds": 0},
            {"deployment_id": "test/PR#1", "stage_name": "ci", "duration_seconds": 0},
        ]

        metrics = compute_vsm_metrics(records)
        # review (7200) > coding (3600), and deploy/ci are 0
        assert metrics["primary_bottleneck"] == "review"

    def test_aggregate_stage_stats(self):
        """AC: Aggregate stats include avg, p50, p95 per stage."""
        records = [
            {"deployment_id": "test/PR#1", "stage_name": "coding", "duration_seconds": 3600},
            {"deployment_id": "test/PR#1", "stage_name": "review", "duration_seconds": 7200},
            {"deployment_id": "test/PR#1", "stage_name": "deploy", "duration_seconds": 900},
            {"deployment_id": "test/PR#1", "stage_name": "ci", "duration_seconds": 0},
            {"deployment_id": "test/PR#2", "stage_name": "coding", "duration_seconds": 7200},
            {"deployment_id": "test/PR#2", "stage_name": "review", "duration_seconds": 14400},
            {"deployment_id": "test/PR#2", "stage_name": "deploy", "duration_seconds": 1800},
            {"deployment_id": "test/PR#2", "stage_name": "ci", "duration_seconds": 0},
        ]

        metrics = compute_vsm_metrics(records)
        stages = metrics["aggregate_stages"]

        assert "coding" in stages
        assert stages["coding"]["sample_count"] == 2
        assert stages["coding"]["avg_seconds"] == 5400  # (3600+7200)/2
        assert stages["coding"]["p50_seconds"] == 7200  # sorted: [3600, 7200], discrete median=7200

        assert "review" in stages
        assert stages["review"]["sample_count"] == 2
        assert (
            stages["review"]["p50_seconds"] == 14400
        )  # sorted: [7200, 14400], discrete median=14400

        assert "deploy" in stages
        assert stages["deploy"]["sample_count"] == 2


# ── Tests: format_duration ─────────────────────────────────────────────────────


class TestFormatDuration:
    def test_seconds(self):
        assert format_duration(30) == "30s"
        assert format_duration(59) == "59s"

    def test_minutes(self):
        assert format_duration(120) == "2.0m"
        assert format_duration(3540) == "59.0m"

    def test_hours(self):
        assert format_duration(3600) == "1.0h"
        assert format_duration(82800) == "23.0h"

    def test_days(self):
        assert format_duration(86400) == "1.0d"
        assert format_duration(172800) == "2.0d"


# ── Tests: parse_args ──────────────────────────────────────────────────────────


class TestParseArgs:
    def test_defaults(self):
        """AC: Default window is 30 days, team is None."""
        args = parse_args([])
        assert args.window == 30
        assert args.team is None
        assert args.pushgateway is None
        assert args.verbose is False
        assert args.json is False

    def test_custom_window(self):
        args = parse_args(["--window", "90"])
        assert args.window == 90

    def test_team_filter(self):
        args = parse_args(["--team", "paruff/test-repo"])
        assert args.team == "paruff/test-repo"

    def test_pushgateway(self):
        args = parse_args(["--pushgateway", "http://localhost:9091"])
        assert args.pushgateway == "http://localhost:9091"

    def test_verbose(self):
        args = parse_args(["--verbose"])
        assert args.verbose is True

    def test_json_output(self):
        args = parse_args(["--json"])
        assert args.json is True

    def test_short_flags(self):
        args = parse_args(["-w", "14", "-t", "paruff/test-repo", "-v"])
        assert args.window == 14
        assert args.team == "paruff/test-repo"
        assert args.verbose is True


# ── Tests: VSIDB (mocked) ──────────────────────────────────────────────────────


class TestVSIDB:
    """Verify VSIDB query construction and data methods."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock asyncpg pool."""
        pool = MagicMock()
        conn = AsyncMock()
        conn.execute = AsyncMock()
        # Make pool.acquire() return an async context manager
        acquire_cm = MagicMock()
        acquire_cm.__aenter__ = AsyncMock(return_value=conn)
        acquire_cm.__aexit__ = AsyncMock(return_value=None)
        pool.acquire = MagicMock(return_value=acquire_cm)
        return pool

    @pytest.fixture
    def db(self, mock_pool):
        """Create a VSIDB instance with mocked pool."""
        db = VSIDB("postgres://localhost:5432/dora_metrics")
        db.pool = mock_pool
        return db

    def test_init_requires_dsn(self):
        """AC: VSIDB raises ValueError without DSN."""
        with (
            patch.dict("os.environ", clear=True),
            pytest.raises(ValueError, match="DATABASE_URL must be set"),
        ):
            VSIDB()

    def test_init_uses_env_var(self):
        """AC: VSIDB reads DATABASE_URL from environment."""
        with patch.dict("os.environ", {"DATABASE_URL": "postgres://env:5432/db"}):
            db = VSIDB()
            assert db.dsn == "postgres://env:5432/db"

    def test_write_stage_breakdown(self, db, mock_pool):
        """AC-02: write_stage_breakdown inserts records."""
        conn = mock_pool.acquire.return_value.__aenter__.return_value
        conn.execute = AsyncMock()

        records = [
            {
                "deployment_id": "test/PR#1",
                "stage_name": "coding",
                "duration_seconds": 3600,
                "status": "success",
                "metadata": {"repo": "test"},
            },
        ]

        count = asyncio.run(db.write_stage_breakdown(records))
        assert count == 1
        conn.execute.assert_called_once()

    def test_write_stage_breakdown_empty(self, db):
        """AC: Empty records list returns 0."""
        count = asyncio.run(db.write_stage_breakdown([]))
        assert count == 0


# ── Tests: print_vsm_table ─────────────────────────────────────────────────────


class TestPrintVSMTable:
    def test_prints_with_data(self, capsys):
        """AC: print_vsm_table produces output with valid data."""
        metrics = {
            "total_journeys": 10,
            "overall_vsm_efficiency_pct": 65.5,
            "primary_bottleneck": "review",
            "aggregate_stages": {
                "coding": {
                    "avg_seconds": 7200,
                    "p50_seconds": 3600,
                    "p95_seconds": 14400,
                    "sample_count": 10,
                },
                "review": {
                    "avg_seconds": 43200,
                    "p50_seconds": 28800,
                    "p95_seconds": 86400,
                    "sample_count": 10,
                },
            },
            "overall_value_add_seconds": 90000,
            "overall_wait_seconds": 432000,
            "overall_total_seconds": 522000,
        }
        print_vsm_table(metrics)
        captured = capsys.readouterr()
        assert "VALUE STREAM INDICATORS" in captured.out
        assert "65.5%" in captured.out
        assert "review" in captured.out
        assert "coding" in captured.out

    def test_prints_empty(self, capsys):
        """AC: print_vsm_table handles empty metrics."""
        metrics = {
            "total_journeys": 0,
            "overall_vsm_efficiency_pct": 0,
            "primary_bottleneck": "unknown",
            "aggregate_stages": {},
            "overall_value_add_seconds": 0,
            "overall_wait_seconds": 0,
            "overall_total_seconds": 0,
        }
        print_vsm_table(metrics)
        captured = capsys.readouterr()
        assert "VALUE STREAM INDICATORS" in captured.out
