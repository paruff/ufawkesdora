"""uFawkesDORA Value Stream Indicators (VSM) Computation.

Computes stage-level lead time breakdown from raw_events and writes
results to the vsi_stage_breakdown table.

Stage definitions (DORA 2025 VSM model):
  - coding:   first_commit_at → pr_opened_at
  - review:   pr_opened_at → pr_merged_at
  - ci:       pr_merged_at → ci_completed_at  (null for v0.1 — CI events not defined)
  - deploy:   pr_merged_at → deployed_at
  - rework:   deployed_at → rework_triggered_at

VSM metrics:
  - value-add time:  coding + CI + deploy  (CI is null for v0.1)
  - wait time:       review + queue
  - VSM efficiency:  value-add / total * 100
  - bottleneck:      stage with highest median duration

Usage:
    python compute/vsi.py --window 30 --team paruff/uFawkesObs
    python compute/vsi.py --window 90 --json
    python compute/vsi.py --window 7 --verbose
"""

import argparse
import asyncio
import json
import logging
import os
from collections import defaultdict
from typing import Any

logger = logging.getLogger("ufawkesdora.vsi")

# Stage definitions for VSM
STAGE_DEFINITIONS = [
    {"name": "coding", "type": "value_add", "requires_ci": False},
    {"name": "review", "type": "wait", "requires_ci": False},
    {"name": "ci", "type": "value_add", "requires_ci": True},
    {"name": "deploy", "type": "value_add", "requires_ci": False},
    {"name": "rework", "type": "wait", "requires_ci": False},
]


class VSIDB:
    """Async PostgreSQL connection for VSM computation."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL")
        if self.dsn is None:
            raise ValueError("DATABASE_URL must be set or dsn argument provided")
        self.pool = None

    async def connect(self):
        import asyncpg

        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    # ── Query methods ─────────────────────────────────────────────────────────

    async def get_merged_prs(self, window_days: int, team: str | None) -> list[dict[str, Any]]:
        """Get all merged PR events with their metadata within the window.

        Returns PR merge events with their paired open event data,
        including first_commit_at and pr_opened_at for stage computation.
        """
        team_clause = f"AND r1.source = '{team}'" if team and team != "all" else ""

        query = f"""
            WITH pr_merged AS (
                SELECT
                    id AS merge_event_id,
                    source AS repo,
                    (metadata->>'pr_number')::INTEGER AS pr_number,
                    (metadata->>'occurred_at')::timestamptz AS merged_at,
                    (metadata->>'first_commit_at')::timestamptz AS first_commit_at,
                    (metadata->>'commit_sha')::TEXT AS commit_sha
                FROM raw_events
                WHERE event_type = 'pr'
                  AND metadata->>'status' = 'merged'
                  AND recorded_at >= NOW() - INTERVAL '{window_days} days'
                {team_clause}
            ),
            pr_opened AS (
                SELECT
                    source AS repo,
                    (metadata->>'pr_number')::INTEGER AS pr_number,
                    (metadata->>'occurred_at')::timestamptz AS opened_at
                FROM raw_events
                WHERE event_type = 'pr'
                  AND metadata->>'status' = 'opened'
                  AND recorded_at >= NOW() - INTERVAL '{window_days} days'
                {team_clause}
            )
            SELECT
                m.repo,
                m.pr_number,
                m.merged_at,
                m.first_commit_at,
                m.commit_sha,
                o.opened_at
            FROM pr_merged m
            LEFT JOIN pr_opened o
                ON m.repo = o.repo AND m.pr_number = o.pr_number
            ORDER BY m.repo, m.merged_at
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def get_deployments(self, window_days: int, team: str | None) -> list[dict[str, Any]]:
        """Get successful deployment events within the window."""
        team_clause = f"AND source = '{team}'" if team and team != "all" else ""

        query = f"""
            SELECT
                id,
                source AS repo,
                (metadata->>'commit_sha')::TEXT AS commit_sha,
                (metadata->>'deployed_at')::timestamptz AS deployed_at,
                recorded_at
            FROM raw_events
            WHERE event_type = 'deployment'
              AND outcome = 'success'
              AND metadata ? 'deployed_at'
              AND recorded_at >= NOW() - INTERVAL '{window_days} days'
            {team_clause}
            ORDER BY source, deployed_at
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def write_stage_breakdown(self, records: list[dict[str, Any]]) -> int:
        """Write stage breakdown records to the vsi_stage_breakdown table.

        Args:
            records: List of dicts with keys: deployment_id, stage_name,
                    duration_seconds, status, metadata.

        Returns:
            Number of records written.
        """
        if not records:
            return 0

        async with self.pool.acquire() as conn:
            for rec in records:
                await conn.execute(
                    """
                    INSERT INTO vsi_stage_breakdown
                        (deployment_id, stage_name, duration_seconds, status, metadata)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    """,
                    rec["deployment_id"],
                    rec["stage_name"],
                    rec["duration_seconds"],
                    rec.get("status", "success"),
                    json.dumps(rec.get("metadata", {})),
                )
        return len(records)

    async def get_stage_summary(self, window_days: int, team: str | None) -> list[dict[str, Any]]:
        """Get aggregate stage statistics from vsi_stage_breakdown."""
        team_clause = ""
        if team and team != "all":
            team_clause = "AND s.deployment_id LIKE $1 || '%'"

        query = f"""
            SELECT
                s.stage_name,
                COUNT(*) AS sample_count,
                AVG(s.duration_seconds)::NUMERIC(10,1) AS avg_duration_s,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY s.duration_seconds)::NUMERIC(10,1) AS p50_duration_s,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY s.duration_seconds)::NUMERIC(10,1) AS p95_duration_s,
                SUM(s.duration_seconds)::NUMERIC(12,1) AS total_duration_s
            FROM vsi_stage_breakdown s
            WHERE s.recorded_at >= NOW() - INTERVAL '{window_days} days'
            {team_clause}
            GROUP BY s.stage_name
            ORDER BY s.stage_name
        """
        params = [team] if team and team != "all" else []

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]


# ── Stage computation ──────────────────────────────────────────────────────────


def compute_deployment_id(repo: str, pr_number: int) -> str:
    """Generate a unique deployment ID from repo and PR number."""
    return f"{repo}/PR#{pr_number}"


def compute_pr_stages(
    prs: list[dict[str, Any]],
    deployments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reconstruct stage durations for each commit-to-deploy journey.

    For each merged PR, find the nearest deployment after merge and
    compute stage durations.

    Stages:
      - coding:   first_commit_at → opened_at
      - review:   opened_at → merged_at
      - deploy:   merged_at → deployed_at (nearest deployment after merge)
      - ci:       None for v0.1 (no CI event schema yet)
      - rework:   None for v0.1 (requires linked rework events)

    Args:
        prs: List of merged PR records with keys: repo, pr_number,
             merged_at, first_commit_at, commit_sha, opened_at.
        deployments: List of deployment records with keys: repo,
                    commit_sha, deployed_at.

    Returns:
        List of stage breakdown records for insertion into vsi_stage_breakdown.
    """
    records: list[dict[str, Any]] = []

    # Index deployments by repo, sorted by time
    deploys_by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for dep in deployments:
        deploys_by_repo[dep["repo"]].append(dep)

    # For each repo, sort deployments by deployed_at
    for repo in deploys_by_repo:
        deploys_by_repo[repo].sort(key=lambda d: d["deployed_at"])

    for pr in prs:
        repo = pr["repo"]
        pr_number = pr["pr_number"]
        dep_id = compute_deployment_id(repo, pr_number)

        merged_at = pr["merged_at"]
        first_commit_at = pr.get("first_commit_at")
        opened_at = pr.get("opened_at")

        if first_commit_at is None or opened_at is None:
            # Cannot compute coding/review without both timestamps
            logger.debug(
                "Skipping PR %s/%s: missing first_commit_at or opened_at",
                repo,
                pr_number,
            )
            continue

        # ── Coding time: first_commit_at → opened_at ────────────────────────
        coding_duration = max(0, int((opened_at - first_commit_at).total_seconds()))
        records.append(
            {
                "deployment_id": dep_id,
                "stage_name": "coding",
                "duration_seconds": coding_duration,
                "status": "success",
                "metadata": {
                    "repo": repo,
                    "pr_number": pr_number,
                    "first_commit_at": first_commit_at.isoformat(),
                    "opened_at": opened_at.isoformat(),
                },
            }
        )

        # ── Review time: opened_at → merged_at ──────────────────────────────
        review_duration = max(0, int((merged_at - opened_at).total_seconds()))
        records.append(
            {
                "deployment_id": dep_id,
                "stage_name": "review",
                "duration_seconds": review_duration,
                "status": "success",
                "metadata": {
                    "repo": repo,
                    "pr_number": pr_number,
                    "opened_at": opened_at.isoformat(),
                    "merged_at": merged_at.isoformat(),
                },
            }
        )

        # ── Deploy time: merged_at → nearest deploy after merge ─────────────
        repo_deploys = deploys_by_repo.get(repo, [])
        deploy_time = None
        deploy_sha = None

        for dep in repo_deploys:
            if dep["deployed_at"] > merged_at:
                deploy_time = dep["deployed_at"]
                deploy_sha = dep.get("commit_sha")
                break

        if deploy_time is not None:
            deploy_duration = max(0, int((deploy_time - merged_at).total_seconds()))
            records.append(
                {
                    "deployment_id": dep_id,
                    "stage_name": "deploy",
                    "duration_seconds": deploy_duration,
                    "status": "success",
                    "metadata": {
                        "repo": repo,
                        "pr_number": pr_number,
                        "merged_at": merged_at.isoformat(),
                        "deployed_at": deploy_time.isoformat(),
                        "commit_sha": deploy_sha or "",
                    },
                }
            )
        else:
            # No deployment found after merge — mark deploy as pending
            records.append(
                {
                    "deployment_id": dep_id,
                    "stage_name": "deploy",
                    "duration_seconds": 0,
                    "status": "pending",
                    "metadata": {
                        "repo": repo,
                        "pr_number": pr_number,
                        "note": "No deployment found after PR merge",
                    },
                }
            )

        # ── CI stage: null for v0.1 (no CI event schema yet) ────────────────
        records.append(
            {
                "deployment_id": dep_id,
                "stage_name": "ci",
                "duration_seconds": 0,
                "status": "skipped",
                "metadata": {
                    "repo": repo,
                    "pr_number": pr_number,
                    "note": "CI stage requires CI event schema (v0.2+)",
                },
            }
        )

    return records


def compute_vsm_metrics(
    stage_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute VSM aggregate metrics from stage breakdown records.

    Groups by deployment_id and computes per-journey metrics.

    Args:
        stage_records: List of stage breakdown records.

    Returns:
        Dict with VSM metrics including per-deployment breakdown and
        repo-level aggregates.
    """
    # Group by deployment_id
    journeys: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "stages": {},
            "total_seconds": 0,
            "value_add_seconds": 0,
            "wait_seconds": 0,
        }
    )

    for rec in stage_records:
        dep_id = rec["deployment_id"]
        stage_name = rec["stage_name"]
        duration = rec["duration_seconds"]

        journeys[dep_id]["stages"][stage_name] = duration
        journeys[dep_id]["total_seconds"] += duration

        if stage_name in ("coding", "deploy"):
            journeys[dep_id]["value_add_seconds"] += duration
        elif stage_name == "review":
            journeys[dep_id]["wait_seconds"] += duration
        # ci is skipped (0 duration), rework not yet implemented

    # Compute per-deployment metrics
    per_deployment: list[dict[str, Any]] = []
    for dep_id, journey in sorted(journeys.items()):
        total = journey["total_seconds"]
        value_add = journey["value_add_seconds"]
        wait = journey["wait_seconds"]

        efficiency = (value_add / total * 100) if total > 0 else 0.0

        # Identify bottleneck for this journey
        stages = journey["stages"]
        bottleneck = max(stages, key=stages.get) if stages else "unknown"

        per_deployment.append(
            {
                "deployment_id": dep_id,
                "stages": stages,
                "total_seconds": total,
                "value_add_seconds": value_add,
                "wait_seconds": wait,
                "vsm_efficiency_pct": round(efficiency, 1),
                "bottleneck": bottleneck,
            }
        )

    # Compute repo-level aggregates
    stage_stats: dict[str, list[int]] = defaultdict(list)
    for rec in stage_records:
        if rec["duration_seconds"] > 0:
            stage_stats[rec["stage_name"]].append(rec["duration_seconds"])

    aggregate_stages: dict[str, dict[str, float]] = {}
    for stage_name, durations in sorted(stage_stats.items()):
        if durations:
            sorted_d = sorted(durations)
            n = len(sorted_d)
            aggregate_stages[stage_name] = {
                "avg_seconds": round(sum(sorted_d) / n, 1),
                "p50_seconds": round(sorted_d[n // 2], 1),
                "p95_seconds": round(sorted_d[int(n * 0.95)], 1),
                "sample_count": n,
            }

    # Identify primary bottleneck (stage with highest median across all journeys)
    primary_bottleneck = "unknown"
    max_median = 0
    for stage_name, stats in aggregate_stages.items():
        if stats["p50_seconds"] > max_median:
            max_median = stats["p50_seconds"]
            primary_bottleneck = stage_name

    # Compute repo-level VSM efficiency
    total_seconds = sum(j["total_seconds"] for j in per_deployment)
    total_value_add = sum(j["value_add_seconds"] for j in per_deployment)
    overall_efficiency = (
        round(total_value_add / total_seconds * 100, 1) if total_seconds > 0 else 0.0
    )

    return {
        "total_journeys": len(per_deployment),
        "per_deployment": per_deployment,
        "aggregate_stages": aggregate_stages,
        "primary_bottleneck": primary_bottleneck,
        "overall_vsm_efficiency_pct": overall_efficiency,
        "overall_value_add_seconds": total_value_add,
        "overall_wait_seconds": sum(j["wait_seconds"] for j in per_deployment),
        "overall_total_seconds": total_seconds,
    }


def format_duration(seconds: int | float) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}m"
    elif seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    else:
        return f"{seconds / 86400:.1f}d"


# ── Orchestrator ───────────────────────────────────────────────────────────────


async def compute_vsi(
    window_days: int,
    team: str | None = None,
    pushgateway: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Compute Value Stream Indicators and write to database.

    Args:
        window_days: Number of days to look back.
        team: Team/repo filter. None or "all" for all teams.
        pushgateway: Prometheus pushgateway URL for metric emission.
        verbose: Enable debug logging.

    Returns:
        Dict with VSM metrics including aggregate stats and bottleneck.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Computing VSM (window=%d days, team=%s)", window_days, team or "all")

    async with VSIDB() as db:
        # Fetch raw data
        prs, deployments = await asyncio.gather(
            db.get_merged_prs(window_days, team),
            db.get_deployments(window_days, team),
        )

        logger.info("Found %d merged PRs, %d deployments", len(prs), len(deployments))

        # Compute stage durations
        stage_records = compute_pr_stages(prs, deployments)
        logger.info("Computed %d stage breakdown records", len(stage_records))

        # Write to vsi_stage_breakdown table
        written = await db.write_stage_breakdown(stage_records)
        logger.info("Wrote %d records to vsi_stage_breakdown", written)

    # Compute VSM aggregates
    vsm_metrics = compute_vsm_metrics(stage_records)

    # Push to Prometheus pushgateway
    if pushgateway:
        await _push_vsm_metrics(vsm_metrics, pushgateway)

    return vsm_metrics


async def _push_vsm_metrics(
    vsm_metrics: dict[str, Any],
    pushgateway_url: str,
):
    """Push VSM metrics to Prometheus pushgateway."""
    import aiohttp

    team_id = "all"
    lines: list[str] = []

    def gauge(name: str, value: float | None, _lines: list[str] = lines) -> None:
        if value is None:
            return
        _lines.append(f"# HELP {name} VSM metric")
        _lines.append(f"# TYPE {name} gauge")
        _lines.append(f'{name}{{team_id="{team_id}"}} {value}')

    # Overall metrics
    gauge("vsm_efficiency_pct", vsm_metrics.get("overall_vsm_efficiency_pct"))
    gauge("vsm_total_journeys", vsm_metrics.get("total_journeys"))
    gauge("vsm_value_add_seconds", vsm_metrics.get("overall_value_add_seconds"))
    gauge("vsm_wait_seconds", vsm_metrics.get("overall_wait_seconds"))
    gauge("vsm_total_seconds", vsm_metrics.get("overall_total_seconds"))

    # Per-stage metrics
    for stage_name, stats in vsm_metrics.get("aggregate_stages", {}).items():
        stage = stage_name.replace("_", "")
        gauge(f"vsm_{stage}_avg_seconds", stats.get("avg_seconds"))
        gauge(f"vsm_{stage}_p50_seconds", stats.get("p50_seconds"))
        gauge(f"vsm_{stage}_p95_seconds", stats.get("p95_seconds"))

    # Bottleneck label
    bottleneck = vsm_metrics.get("primary_bottleneck", "unknown")
    lines.append(f'vsm_primary_bottleneck{{team_id="{team_id}",stage="{bottleneck}"}} 1')

    payload = "\n".join(lines)
    job_name = "ufawkesdora/vsm"

    try:
        async with aiohttp.ClientSession() as session:
            url = f"{pushgateway_url.rstrip('/')}/metrics/job/{job_name}"
            async with session.put(url, data=payload) as resp:
                if resp.status not in (200, 202):
                    logger.warning("Pushgateway returned %d for VSM", resp.status)
                else:
                    logger.debug("Pushed VSM metrics")
    except Exception as e:
        logger.warning("Failed to push VSM metrics: %s", e)


# ── CLI ────────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute Value Stream Indicators from PostgreSQL/TimescaleDB",
    )
    parser.add_argument(
        "--window",
        "-w",
        type=int,
        default=30,
        help="Number of days to look back (default: 30)",
    )
    parser.add_argument(
        "--team",
        "-t",
        default=None,
        help="Team/repo filter (default: all teams)",
    )
    parser.add_argument(
        "--pushgateway",
        "-p",
        default=None,
        help="Prometheus pushgateway URL (e.g. http://localhost:9091)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (default: table format)",
    )
    return parser.parse_args(argv)


def print_vsm_table(vsm_metrics: dict[str, Any]):
    """Pretty-print VSM metrics as a table."""
    print(f"\n{'═' * 60}")
    print("  VALUE STREAM INDICATORS")
    print(f"{'═' * 60}")
    print(f"  Total journeys:     {vsm_metrics.get('total_journeys', 0)}")
    print(f"  Overall efficiency: {vsm_metrics.get('overall_vsm_efficiency_pct', 0):.1f}%")
    print(f"  Primary bottleneck: {vsm_metrics.get('primary_bottleneck', 'unknown')}")
    print(f"{'─' * 60}")

    # Stage breakdown
    stages = vsm_metrics.get("aggregate_stages", {})
    if stages:
        print(f"\n  {'Stage':<12} {'Avg':<12} {'P50':<12} {'P95':<12} {'Count':<8}")
        print(f"  {'─' * 56}")
        for stage_name, stats in sorted(stages.items()):
            print(
                f"  {stage_name:<12}"
                f" {format_duration(stats['avg_seconds']):<12}"
                f" {format_duration(stats['p50_seconds']):<12}"
                f" {format_duration(stats['p95_seconds']):<12}"
                f" {stats['sample_count']:<8}"
            )

    # Timing summary
    print(f"\n  {'─' * 40}")
    print(f"  Value-add time: {format_duration(vsm_metrics.get('overall_value_add_seconds', 0))}")
    print(f"  Wait time:      {format_duration(vsm_metrics.get('overall_wait_seconds', 0))}")
    print(f"  Total time:     {format_duration(vsm_metrics.get('overall_total_seconds', 0))}")
    print(f"{'═' * 60}\n")


async def main_async(args: argparse.Namespace):
    results = await compute_vsi(
        window_days=args.window,
        team=args.team,
        pushgateway=args.pushgateway,
        verbose=args.verbose,
    )

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print_vsm_table(results)


def main():
    """CLI entrypoint."""
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
