"""uFawkesDORA DORA Metrics Computation.

Computes all five DORA delivery metrics from the raw_events table and
writes results to dora_snapshots + Prometheus pushgateway.

Metrics (DORA 2025):
  - Deployment Frequency (deploys/week)
  - Lead Time for Changes (P50/P95 hours)
  - FDRT — Failure Deployment Recovery Time (deployment-gap, not incident MTTR)
  - Change Failure Rate (% of deployments that fail or rollback)
  - Rework Rate (user-visible rework deployments / total deployments)

DORA 2025 classification:
  - FDRT moves from Stability to Throughput
  - Rework Rate added as Stability metric
  - FDRT is deployment-gap, NOT incident-resolution gap

Usage:
    python compute/metrics.py --window 30 --team paruff/uFawkesObs
    python compute/metrics.py --window 90 --pushgateway http://localhost:9091
    python compute/metrics.py --window 7 --team all --verbose
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("ufawkesdora.metrics")

# DORA 2025 tier thresholds
# Source: DORA State of DevOps Report 2025
TIER_THRESHOLDS = {
    "deployment_frequency": {
        "elite": (lambda v: v >= 7.0),           # Multiple deploys/day = 7+/week
        "high": (lambda v: 1.0 <= v < 7.0),       # Daily to weekly
        "medium": (lambda v: 0.25 <= v < 1.0),    # Weekly to monthly = ~1/month
        "low": (lambda v: v < 0.25),              # Less than monthly (~1/quarter = 0.08)
    },
    "lead_time": {
        "elite": (lambda v: v <= 1.0),             # Less than 1 hour
        "high": (lambda v: 1.0 < v <= 24.0),       # 1 day
        "medium": (lambda v: 24.0 < v <= 168.0),   # 1 week
        "low": (lambda v: v > 168.0),              # More than 1 week
    },
    "fdrt": {
        "elite": (lambda v: v <= 1.0),             # Less than 1 hour
        "high": (lambda v: 1.0 < v <= 24.0),       # 1 day
        "medium": (lambda v: 24.0 < v <= 168.0),   # 1 week
        "low": (lambda v: v > 168.0),              # More than 1 week
    },
    "cfr": {
        "elite": (lambda v: v <= 0.05),            # <= 5%
        "high": (lambda v: 0.05 < v <= 0.10),      # 10%
        "medium": (lambda v: 0.10 < v <= 0.15),    # 15%
        "low": (lambda v: v > 0.15),               # > 15%
    },
    "rework_rate": {
        "elite": (lambda v: v <= 0.05),            # <= 5%
        "high": (lambda v: 0.05 < v <= 0.10),      # 10%
        "medium": (lambda v: 0.10 < v <= 0.15),    # 15%
        "low": (lambda v: v > 0.15),               # > 15%
    },
}

DORA_TIERS = ["elite", "high", "medium", "low"]


def classify_tier(metric_name: str, value: float | None) -> str:
    """Classify a metric value into a DORA 2025 tier.

    Args:
        metric_name: One of ``deployment_frequency``, ``lead_time``,
            ``fdrt``, ``cfr``, ``rework_rate``.
        value: The metric value, or None.

    Returns:
        One of ``elite``, ``high``, ``medium``, ``low``, ``unknown``.
    """
    if value is None:
        return "unknown"
    thresholds = TIER_THRESHOLDS.get(metric_name)
    if not thresholds:
        return "unknown"
    for tier in DORA_TIERS:
        if thresholds[tier](value):
            return tier
    return "unknown"


# ── Database layer ─────────────────────────────────────────────────────────────


class MetricsDB:
    """Async TimescaleDB connection for metric computation."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get(
            "DATABASE_URL",
            "postgresql://dora_app:dora_app@localhost:5432/dora_metrics",
        )
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

    # ── Query builders ─────────────────────────────────────────────────────

    def _window_start(self, window_days: int) -> str:
        return f"NOW() - INTERVAL '{window_days} days'"

    async def deployment_frequency(
        self, window_days: int, team: str | None
    ) -> list[dict[str, Any]]:
        """Deployment Frequency: deploys/week per team over the window."""
        team_clause = f"AND source = '{team}'" if team and team != "all" else ""
        query = f"""
            SELECT
                source AS team_id,
                COUNT(*)::NUMERIC / GREATEST({window_days} / 7.0, 1.0) AS deploys_per_week
            FROM raw_events
            WHERE event_type = 'deployment'
              AND outcome = 'success'
              AND recorded_at >= {self._window_start(window_days)}
            {team_clause}
            GROUP BY source
            ORDER BY source
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def lead_time(
        self, window_days: int, team: str | None
    ) -> list[dict[str, Any]]:
        """Lead Time for Changes: P50 and P95 in hours.

        Uses ``metadata->>'first_commit_at'`` as the code committed timestamp.
        Falls back to ``metadata->>'pr_merged_at'`` as a proxy when
        ``first_commit_at`` is not available — the ``proxy_metrics`` flag
        is set to true in this case.

        DORA defers to PR merge time only when first commit is unavailable.
        """
        team_clause = f"AND source = '{team}'" if team and team != "all" else ""

        # We compute two queries:
        # Query A: deployments with first_commit_at (exact, no proxy)
        # Query B: deployments with pr_merged_at but NO first_commit_at (proxy)

        query_a = f"""
            SELECT
                source AS team_id,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY lead_time) AS p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY lead_time) AS p95,
                FALSE AS proxy_used
            FROM (
                SELECT
                    source,
                    EXTRACT(EPOCH FROM (
                        (metadata->>'deployed_at')::timestamptz -
                        (metadata->>'first_commit_at')::timestamptz
                    )) / 3600 AS lead_time
                FROM raw_events
                WHERE event_type = 'deployment'
                  AND outcome = 'success'
                  AND metadata ? 'first_commit_at'
                  AND metadata ? 'deployed_at'
                  AND recorded_at >= {self._window_start(window_days)}
                {team_clause}
            ) sub
            GROUP BY source
        """

        query_b = f"""
            SELECT
                source AS team_id,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY lead_time) AS p50,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY lead_time) AS p95,
                TRUE AS proxy_used
            FROM (
                SELECT
                    source,
                    EXTRACT(EPOCH FROM (
                        (metadata->>'deployed_at')::timestamptz -
                        (metadata->>'pr_merged_at')::timestamptz
                    )) / 3600 AS lead_time
                FROM raw_events
                WHERE event_type = 'deployment'
                  AND outcome = 'success'
                  AND NOT (metadata ? 'first_commit_at')
                  AND metadata ? 'pr_merged_at'
                  AND metadata ? 'deployed_at'
                  AND recorded_at >= {self._window_start(window_days)}
                {team_clause}
            ) sub
            GROUP BY source
        """

        async with self.pool.acquire() as conn:
            rows_a = await conn.fetch(query_a)
            rows_b = await conn.fetch(query_b)
            result = {}
            for r in rows_a:
                d = dict(r)
                d["proxy_metrics"] = False
                result[d["team_id"]] = d
            for r in rows_b:
                d = dict(r)
                d["proxy_metrics"] = True
                if d["team_id"] in result:
                    # Merge: combine exact + proxy data
                    existing = result[d["team_id"]]
                    # Use proxy to fill null p50/p95 from query_a
                    if existing.get("p50") is None and d.get("p50") is not None:
                        existing["p50"] = d["p50"]
                        existing["proxy_metrics"] = True
                    if existing.get("p95") is None and d.get("p95") is not None:
                        existing["p95"] = d["p95"]
                else:
                    result[d["team_id"]] = d
            return list(result.values())

    async def fdrt(
        self, window_days: int, team: str | None
    ) -> list[dict[str, Any]]:
        """Failure Deployment Recovery Time (FDRT).

        DORA 2025 reclassification: FDRT is the time between a failed deployment
        and the next successful deployment of the SAME service (team).
        This is a deployment-gap metric, NOT an incident-resolution metric.

        Citations:
          - DORA State of DevOps Report 2025, "Throughput" chapter:
            "FDRT measures the time from a failed deployment to the next
             successful deployment of the same service, reflecting the team's
             ability to recover from deployment failures."

        Returns null fdrt for teams that have no recovery in the window.
        """
        team_clause = f"AND source = '{team}'" if team and team != "all" else ""

        query = f"""
            WITH ordered_deployments AS (
                SELECT
                    source AS team_id,
                    outcome,
                    recorded_at,
                    LEAD(recorded_at) OVER (
                        PARTITION BY source
                        ORDER BY recorded_at
                    ) AS next_deploy_at
                FROM raw_events
                WHERE event_type = 'deployment'
                  AND recorded_at >= {self._window_start(window_days)}
                {team_clause}
            ),
            fdrt_gaps AS (
                SELECT
                    team_id,
                    EXTRACT(EPOCH FROM (next_deploy_at - recorded_at)) / 3600 AS gap_hours
                FROM ordered_deployments
                WHERE outcome IN ('failure', 'rollback')
                  AND next_deploy_at IS NOT NULL
                  AND (
                      -- Ensure the recovery was a success
                      EXISTS (
                          SELECT 1 FROM raw_events r2
                          WHERE r2.event_type = 'deployment'
                            AND r2.source = ordered_deployments.team_id
                            AND r2.outcome = 'success'
                            AND r2.recorded_at = ordered_deployments.next_deploy_at
                      )
                  )
            )
            SELECT
                team_id,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY gap_hours) AS p50_fdrt_hours
            FROM fdrt_gaps
            GROUP BY team_id
            ORDER BY team_id
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def change_failure_rate(
        self, window_days: int, team: str | None
    ) -> list[dict[str, Any]]:
        """Change Failure Rate: % of deployments that fail or rollback."""
        team_clause = f"AND source = '{team}'" if team and team != "all" else ""
        query = f"""
            SELECT
                source AS team_id,
                COUNT(*) FILTER (WHERE outcome IN ('failure', 'rollback')) * 1.0
                    / NULLIF(COUNT(*), 0) AS cfr
            FROM raw_events
            WHERE event_type = 'deployment'
              AND recorded_at >= {self._window_start(window_days)}
            {team_clause}
            GROUP BY source
            ORDER BY source
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def rework_rate(
        self, window_days: int, team: str | None
    ) -> list[dict[str, Any]]:
        """Rework Rate: user-visible rework events / total deployments.

        Only counts rework events where ``user_visible`` is true — hotfixes
        for internal issues (false) are excluded per DORA 2025 guidance.
        """
        team_clause = ""
        if team and team != "all":
            team_clause = f"AND d.source = '{team}'"

        query = f"""
            SELECT
                d.source AS team_id,
                COUNT(DISTINCT r.id) * 1.0
                    / NULLIF(COUNT(DISTINCT d.id), 0) AS rework_pct
            FROM raw_events d
            LEFT JOIN raw_events r
                ON r.event_type = 'rework'
                AND r.source = d.source
                AND r.metadata->>'deployment_sha' = d.metadata->>'commit_sha'
                AND (r.metadata->>'user_visible')::boolean = TRUE
                AND r.recorded_at >= {self._window_start(window_days)}
            WHERE d.event_type = 'deployment'
              AND d.recorded_at >= {self._window_start(window_days)}
            {team_clause}
            GROUP BY d.source
            ORDER BY d.source
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]


# ── Metric computation orchestrator ────────────────────────────────────────────


async def compute_all_metrics(
    window_days: int,
    team: str | None = None,
    pushgateway: str | None = None,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Compute all DORA metrics and write results.

    Args:
        window_days: Number of days to look back.
        team: Team/repo filter. ``None`` or ``"all"`` for all teams.
        pushgateway: Prometheus pushgateway URL for metric emission.
        verbose: Enable debug logging.

    Returns:
        List of result dicts, one per team.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Computing DORA metrics (window=%d days, team=%s)", window_days, team or "all")

    async with MetricsDB() as db:
        # Run all metric queries in parallel
        df, lt, fdrt_res, cfr, rr = await asyncio.gather(
            db.deployment_frequency(window_days, team),
            db.lead_time(window_days, team),
            db.fdrt(window_days, team),
            db.change_failure_rate(window_days, team),
            db.rework_rate(window_days, team),
        )

    # Merge results by team
    results = _merge_team_results(df, lt, fdrt_res, cfr, rr)

    # Write to dora_snapshots
    async with MetricsDB() as db:
        await _write_snapshots(db, results, window_days)

    # Push to Prometheus pushgateway
    if pushgateway:
        await _push_metrics(results, pushgateway)

    return results


def _ensure_team_entry(teams: dict[str, dict], team_id: str, proxy: bool = False) -> dict:
    """Get or create a team entry, initializing all metric keys to None."""
    ALL_METRIC_KEYS = [
        "deployment_frequency", "lead_time_p50_hours", "lead_time_p95_hours",
        "fdrt_p50_hours", "change_failure_rate", "rework_rate_pct",
    ]
    if team_id not in teams:
        entry = {"team_id": team_id, "proxy_metrics": proxy}
        for k in ALL_METRIC_KEYS:
            entry[k] = None
        teams[team_id] = entry
    return teams[team_id]


def _merge_team_results(
    df: list[dict],
    lt: list[dict],
    fdrt_res: list[dict],
    cfr: list[dict],
    rr: list[dict],
) -> list[dict[str, Any]]:
    """Merge per-team metric results into unified records."""
    teams: dict[str, dict] = {}

    for row in df:
        tid = row["team_id"]
        entry = _ensure_team_entry(teams, tid)
        entry["deployment_frequency"] = float(row["deploys_per_week"])
        entry["proxy_metrics"] = row.get("proxy_metrics", False)

    for row in lt:
        tid = row["team_id"]
        entry = _ensure_team_entry(teams, tid, proxy=row.get("proxy_used", False))
        entry["lead_time_p50_hours"] = float(row["p50"]) if row["p50"] is not None else None
        entry["lead_time_p95_hours"] = float(row["p95"]) if row["p95"] is not None else None
        if row.get("proxy_used"):
            entry["proxy_metrics"] = True

    for row in fdrt_res:
        tid = row["team_id"]
        entry = _ensure_team_entry(teams, tid)
        entry["fdrt_p50_hours"] = float(row["p50_fdrt_hours"]) if row["p50_fdrt_hours"] is not None else None

    for row in cfr:
        tid = row["team_id"]
        entry = _ensure_team_entry(teams, tid)
        entry["change_failure_rate"] = float(row["cfr"]) if row["cfr"] is not None else None

    for row in rr:
        tid = row["team_id"]
        entry = _ensure_team_entry(teams, tid)
        entry["rework_rate_pct"] = float(row["rework_pct"]) if row["rework_pct"] is not None else None

    # Add DORA tiers
    for tid, entry in teams.items():
        entry["dora_tier_deployment_frequency"] = classify_tier(
            "deployment_frequency", entry.get("deployment_frequency")
        )
        entry["dora_tier_lead_time"] = classify_tier(
            "lead_time", entry.get("lead_time_p50_hours")
        )
        entry["dora_tier_fdrt"] = classify_tier(
            "fdrt", entry.get("fdrt_p50_hours")
        )
        entry["dora_tier_cfr"] = classify_tier(
            "cfr", entry.get("change_failure_rate")
        )
        entry["dora_tier_rework_rate"] = classify_tier(
            "rework_rate", entry.get("rework_rate_pct")
        )

    return list(teams.values())


async def _write_snapshots(
    db: MetricsDB,
    results: list[dict[str, Any]],
    window_days: int,
):
    """Write metric results to the dora_snapshots hypertable."""
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=window_days)

    for record in results:
        await db.pool.execute(
            """
            INSERT INTO dora_snapshots
                (team_id, deployment_frequency, lead_time_hours,
                 change_failure_rate, time_to_restore_hours,
                 fdrt_hours, rework_rate_pct, proxy_metrics, dora_tier,
                 snapshot_window_start, snapshot_window_end, recorded_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
            """,
            record["team_id"],
            record.get("deployment_frequency", 0),
            record.get("lead_time_p50_hours"),
            record.get("change_failure_rate"),
            None,  # time_to_restore_hours — deprecated in favor of fdrt
            record.get("fdrt_p50_hours"),
            record.get("rework_rate_pct"),
            record.get("proxy_metrics", False),
            record.get("dora_tier_deployment_frequency", "unknown"),
            window_start,
            window_end,
        )


async def _push_metrics(
    results: list[dict[str, Any]],
    pushgateway_url: str,
):
    """Push DORA metrics to Prometheus pushgateway.

    Each metric gets a separate push with team_id, tier labels.
    """
    import aiohttp

    for record in results:
        tid = record["team_id"]
        tier = record.get("dora_tier_deployment_frequency", "unknown")

        # Build Prometheus text format payload
        lines = []

        def gauge(name: str, value: float | None, tier_label: str | None = None):
            if value is None:
                return
            labels = f'team_id="{tid}"'
            if tier_label:
                labels += f',tier="{tier_label}"'
            lines.append(f"# HELP {name} DORA metric")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name}{{{labels}}} {value}")

        gauge("dora_deployment_frequency_per_week", record.get("deployment_frequency"), tier)
        gauge("dora_lead_time_p50_hours", record.get("lead_time_p50_hours"),
              record.get("dora_tier_lead_time"))
        gauge("dora_lead_time_p95_hours", record.get("lead_time_p95_hours"))
        gauge("dora_fdrt_p50_hours", record.get("fdrt_p50_hours"),
              record.get("dora_tier_fdrt"))
        gauge("dora_cfr_pct", record.get("change_failure_rate"),
              record.get("dora_tier_cfr"))
        gauge("dora_rework_rate_pct", record.get("rework_rate_pct"),
              record.get("dora_tier_rework_rate"))

        payload = "\n".join(lines)
        job_name = f"ufawkesdora/{tid.replace('/', '_')}"

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{pushgateway_url.rstrip('/')}/metrics/job/{job_name}"
                async with session.put(url, data=payload) as resp:
                    if resp.status not in (200, 202):
                        logger.warning(
                            "Pushgateway returned %d for %s", resp.status, job_name
                        )
                    else:
                        logger.debug("Pushed metrics for %s", tid)
        except Exception as e:
            logger.warning("Failed to push metrics for %s: %s", tid, e)


# ── CLI ────────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute DORA delivery metrics from PostgreSQL/TimescaleDB",
    )
    parser.add_argument(
        "--window", "-w",
        type=int,
        default=30,
        help="Number of days to look back (default: 30)",
    )
    parser.add_argument(
        "--team", "-t",
        default=None,
        help="Team/repo filter (default: all teams)",
    )
    parser.add_argument(
        "--pushgateway", "-p",
        default=None,
        help="Prometheus pushgateway URL (e.g. http://localhost:9091)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (default: table format)",
    )
    return parser.parse_args(argv)


async def main_async(args: argparse.Namespace):
    results = await compute_all_metrics(
        window_days=args.window,
        team=args.team,
        pushgateway=args.pushgateway,
        verbose=args.verbose,
    )

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        _print_table(results)


def _print_table(results: list[dict]):
    """Pretty-print metrics as a table."""
    if not results:
        print("No results found.")
        return

    header = (
        f"{'Team':<30} {'DF/week':<10} {'LT P50h':<10} {'LT P95h':<10} "
        f"{'FDRT P50h':<10} {'CFR %':<10} {'Rework %':<10} {'Tier':<12}"
    )
    print(header)
    print("-" * len(header))

    for r in results:
        df = f"{r.get('deployment_frequency', 0):.2f}" if r.get('deployment_frequency') is not None else "N/A"
        lt_p50 = f"{r.get('lead_time_p50_hours', 0):.1f}" if r.get('lead_time_p50_hours') is not None else "N/A"
        lt_p95 = f"{r.get('lead_time_p95_hours', 0):.1f}" if r.get('lead_time_p95_hours') is not None else "N/A"
        fdrt = f"{r.get('fdrt_p50_hours', 0):.1f}" if r.get('fdrt_p50_hours') is not None else "N/A"
        cfr = f"{r.get('change_failure_rate', 0)*100:.1f}" if r.get('change_failure_rate') is not None else "N/A"
        rr = f"{r.get('rework_rate_pct', 0)*100:.1f}" if r.get('rework_rate_pct') is not None else "N/A"
        tier = r.get("dora_tier_deployment_frequency", "N/A")
        print(
            f"{r['team_id']:<30} {df:<10} {lt_p50:<10} {lt_p95:<10} "
            f"{fdrt:<10} {cfr:<10} {rr:<10} {tier:<12}"
        )


def main():
    """CLI entrypoint."""
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()