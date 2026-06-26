"""uFawkesDORA Seven Archetype Classifier.

Classifies a team into one of the seven 2025 DORA archetypes using delivery
metrics from dora_snapshots AND optional wellbeing scores from
wellbeing_surveys. Writes results to the archetype_history table.

Design:
  The classifier uses a centroid-based approach. Each archetype is defined by
  a centroid position in a 5-dimensional metric space (Deployment Frequency,
  Lead Time, FDRT, CFR, Rework Rate) plus an optional wellbeing dimension.
  Metrics are normalized to 0-1 where 1 = best (DORA "good" direction).

  The team's observed metrics are projected into the same space, and the
  archetype with the smallest Euclidean distance is selected. Confidence is
  derived from the inverse of the normalized distance.

  When no wellbeing survey data is available for the period, the classifier
  falls back to metrics-only with confidence capped at 0.65 per the spec
  (metrics alone cannot reliably distinguish archetypes that differ primarily
  on wellbeing).

References:
  - DORA State of DevOps Report 2025: Seven Team Archetypes
  - DORA 2025 reclassification: FDRT moved to Throughput dimension
  - Rework Rate added as Stability metric (user-visible rework only)

Usage:
    python compute/archetype.py --team paruff/uFawkesObs
    python compute/archetype.py --team paruff/uFawkesObs --quarter 2026-Q2
    python compute/archetype.py --team paruff/uFawkesObs --json
"""

import argparse
import asyncio
import logging
import math
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("ufawkesdora.archetype")

# ═══════════════════════════════════════════════════════════════════════════════
# Archetype Centroids
# ═══════════════════════════════════════════════════════════════════════════════
#
# Each centroid is a 6-dimensional point (5 metrics + wellbeing) where each
# dimension is normalized 0-1 (1 = best).
#
# Metric mapping (raw → 0-1 best direction):
#   deployment_frequency:  higher = better  → v / (v + threshold)
#   lead_time_hours:       lower  = better  → 1 - min(v / threshold, 1)
#   fdrt_hours:            lower  = better  → 1 - min(v / threshold, 1)
#   change_failure_rate:   lower  = better  → 1 - min(v / threshold, 1)
#   rework_rate_pct:       lower  = better  → 1 - min(v / threshold, 1)
#   wellbeing_score:       higher = better  → v / 5.0
#
# Centroids derived from the qualitative archetype descriptions in the
# DORA 2025 State of DevOps Report. Exact centroid positions are design
# choices calibrated to reproduce the qualitative archetype signatures.
#
# NOTE: The seventh archetype name and definition remain unconfirmed pending
# primary-source verification. It is omitted from classification until then.
# See: docs/spec/specification.md §3

ARCHETYPE_DEFINITIONS = {
    "Harmonious high-achievers": {
        # Signature: High throughput + low instability + high wellbeing
        # Normalised from: DF=10-30/wk (0.42-0.68), LT=1-4h (0.98-0.99),
        # FDRT=0.5-2h (0.99), CFR=2-5% (0.83-0.93), RR=2-5% (0.83-0.93),
        # WB avg=4-5 (0.80-1.0)
        "centroid": {
            "deployment_frequency": 0.55,
            "lead_time": 0.98,
            "fdrt": 0.99,
            "change_failure_rate": 0.88,
            "rework_rate": 0.88,
            "wellbeing": 0.90,
        },
        "description": (
            "Teams that achieve both high performance and high wellbeing. "
            "They ship frequently, recover quickly, maintain quality, and "
            "report strong job satisfaction. This is the aspirational archetype."
        ),
        "recommendations": [
            "Share your practices with other teams through Dojo sessions",
            "Invest in platform engineering to amplify your delivery velocity",
            "Mentor other archetypes — your practices are proven and sustainable",
        ],
    },
    "Pragmatic performers": {
        # Signature: High speed/stability + lower engagement
        # Normalised from: DF=5-15/wk (0.26-0.52), LT=2-8h (0.95-0.99),
        # FDRT=2-12h (0.93-0.99), CFR=5-10% (0.67-0.83), RR=5-12% (0.60-0.83),
        # WB avg=2.5-3.5 (0.50-0.70)
        "centroid": {
            "deployment_frequency": 0.40,
            "lead_time": 0.97,
            "fdrt": 0.96,
            "change_failure_rate": 0.75,
            "rework_rate": 0.72,
            "wellbeing": 0.55,
        },
        "description": (
            "Teams that deliver reliably but report lower engagement or "
            "wellbeing. Performance metrics are strong, but the human side "
            "needs attention to prevent burnout attrition."
        ),
        "recommendations": [
            "Run a quarterly wellbeing survey to identify engagement gaps",
            "Review team workload — strong metrics may mask unsustainable pace",
            "Invest in team autonomy and purpose to boost engagement",
        ],
    },
    "Stable and methodical": {
        # Signature: High quality + sustainable pace + lower throughput
        # Normalised from: DF=2-8/wk (0.13-0.36), LT=12-48h (0.71-0.93),
        # FDRT=1-4h (0.98-0.99), CFR=1-3% (0.90-0.97), RR=2-5% (0.83-0.93),
        # WB avg=3-4 (0.60-0.80)
        "centroid": {
            "deployment_frequency": 0.25,
            "lead_time": 0.82,
            "fdrt": 0.98,
            "change_failure_rate": 0.94,
            "rework_rate": 0.88,
            "wellbeing": 0.70,
        },
        "description": (
            "Teams that emphasise quality and sustainability over raw throughput. "
            "Change failure rate and rework are low; deployments are deliberate "
            "and well-tested. This is a healthy, sustainable pattern."
        ),
        "recommendations": [
            "Optimise for throughput without sacrificing quality — consider trunk-based development",
            "Review deployment pipeline for automation opportunities to increase cadence",
            "Your quality practices are excellent — formalise them as team standards",
        ],
    },
    "Constrained by process": {
        # Signature: Stable systems + process overhead consuming capacity
        # Normalised from: DF=1-4/wk (0.07-0.22), LT=48-168h (0.0-0.71),
        # FDRT=12-48h (0.71-0.93), CFR=5-15% (0.50-0.83), RR=8-18% (0.40-0.73),
        # WB avg=2-3 (0.40-0.60)
        "centroid": {
            "deployment_frequency": 0.15,
            "lead_time": 0.35,
            "fdrt": 0.82,
            "change_failure_rate": 0.66,
            "rework_rate": 0.56,
            "wellbeing": 0.48,
        },
        "description": (
            "Teams burdened by process overhead that consumes capacity without "
            "adding quality. Lead time is disproportionately high relative to "
            "change failure rate — indicating process friction, not quality gates."
        ),
        "recommendations": [
            "Audit your change review process — is every step adding value?",
            "Reduce handoffs between teams; stream-align teams where possible",
            "Implement a value stream mapping exercise to identify bottlenecks",
        ],
    },
    "Legacy bottleneck": {
        # Signature: Reactive, unstable systems + low morale
        # Normalised from: DF=0.1-1/wk (0.007-0.07), LT=72-168h (0.0-0.57),
        # FDRT=48-168h (0.0-0.71), CFR=15-30% (0.0-0.50), RR=15-30% (0.0-0.50),
        # WB avg=1.5-3 (0.30-0.60)
        "centroid": {
            "deployment_frequency": 0.04,
            "lead_time": 0.20,
            "fdrt": 0.30,
            "change_failure_rate": 0.25,
            "rework_rate": 0.25,
            "wellbeing": 0.35,
        },
        "description": (
            "Teams maintaining legacy systems that are reactive, unstable, "
            "and demoralising. All DORA metrics are poor, and the team reports "
            "low wellbeing. This archetype needs structural intervention."
        ),
        "recommendations": [
            "Prioritise reliability over features — allocate 30% capacity to reducing tech debt",
            "Implement feature flags to decouple deployment from release",
            "Consider a 'boring technology' strategy to reduce cognitive load",
        ],
    },
    "High impact, low cadence": {
        # Signature: High-value output + low throughput + high instability
        # Normalised from: DF=0.5-3/wk (0.03-0.18), LT=24-96h (0.43-0.86),
        # FDRT=24-96h (0.43-0.86), CFR=10-25% (0.17-0.67), RR=10-20% (0.33-0.67),
        # WB avg=2.5-3.5 (0.50-0.70)
        "centroid": {
            "deployment_frequency": 0.10,
            "lead_time": 0.60,
            "fdrt": 0.55,
            "change_failure_rate": 0.40,
            "rework_rate": 0.50,
            "wellbeing": 0.60,
        },
        "description": (
            "Teams doing high-value, complex work that inherently limits "
            "cadence. Each deployment carries significant risk, and the team "
            "struggles to recover quickly from failures. The work matters, "
            "but the delivery pattern is unstable."
        ),
        "recommendations": [
            "Break work into smaller, independently deployable increments",
            "Invest in test automation to reduce deployment risk",
            "Consider canary deployments or blue/green to reduce blast radius",
        ],
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# Normalisation thresholds
# ═══════════════════════════════════════════════════════════════════════════════
# These thresholds represent the value at which a metric is considered "fully
# good" (score = 1.0) for normalisation purposes. Values beyond the threshold
# are clamped at 0 (worst) or 1 (best) depending on direction.

METRIC_THRESHOLDS = {
    "deployment_frequency": 14.0,  # 14 deploys/week = "fully good"
    "lead_time": 168.0,  # 1 week = "fully bad" (clamped at 0)
    "fdrt": 168.0,  # 1 week = "fully bad"
    "change_failure_rate": 0.30,  # 30% CFR = "fully bad"
    "rework_rate": 0.30,  # 30% rework = "fully bad"
}

ARCHETYPE_ORDER = [
    "Harmonious high-achievers",
    "Pragmatic performers",
    "Stable and methodical",
    "Constrained by process",
    "Legacy bottleneck",
    "High impact, low cadence",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Metric Normalisation
# ═══════════════════════════════════════════════════════════════════════════════


def normalise_metric(raw_value: float | None, threshold: float) -> float:
    """Normalise a metric to 0-1 where 1 = best (DORA good direction).

    Higher-is-better metrics (deployment_frequency): v / (v + threshold)
    Lower-is-better metrics (lead_time, fdrt, cfr, rework): 1 - min(v / threshold, 1)
    """
    if raw_value is None:
        return 0.0
    # deployment_frequency is higher-is-better; all others are lower-is-better
    # We identify deployment_frequency as the only higher-is-better metric
    return raw_value / (raw_value + threshold)


def normalise_lower_is_better(raw_value: float | None, threshold: float) -> float:
    """Normalise where lower values are better (LT, FDRT, CFR, Rework)."""
    if raw_value is None:
        return 0.0
    ratio = raw_value / threshold if threshold > 0 else 0.0
    return max(0.0, 1.0 - ratio)


def normalise_wellbeing(scores: list[int]) -> float:
    """Normalise wellbeing survey scores to 0-1.

    Five questions, each scored 1-5. Average across all respondents and
    questions, divided by 5.
    """
    if not scores:
        return 0.0
    return sum(scores) / (len(scores) * 5.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Centroid Distance & Classification
# ═══════════════════════════════════════════════════════════════════════════════


def build_team_vector(
    snapshot: dict[str, Any],
    wellbeing_score: float | None,
) -> dict[str, float]:
    """Build a normalised 6-dimensional vector for a team's observed metrics.

    Dimensions: deployment_frequency, lead_time, fdrt, change_failure_rate,
    rework_rate, wellbeing (or 0.5 if no wellbeing data — neutral prior).

    Args:
        snapshot: Row from dora_snapshots.
        wellbeing_score: Normalised wellbeing score (0-1), or None.

    Returns:
        Dict of dimension → normalised value (0-1).
    """
    df_raw = snapshot.get("deployment_frequency")
    lt_raw = snapshot.get("lead_time_hours")
    fdrt_raw = snapshot.get("fdrt_hours")
    cfr_raw = snapshot.get("change_failure_rate")
    rr_raw = snapshot.get("rework_rate_pct")

    vector = {
        "deployment_frequency": normalise_metric(df_raw, METRIC_THRESHOLDS["deployment_frequency"]),
        "lead_time": normalise_lower_is_better(lt_raw, METRIC_THRESHOLDS["lead_time"]),
        "fdrt": normalise_lower_is_better(fdrt_raw, METRIC_THRESHOLDS["fdrt"]),
        "change_failure_rate": normalise_lower_is_better(
            cfr_raw, METRIC_THRESHOLDS["change_failure_rate"]
        ),
        "rework_rate": normalise_lower_is_better(rr_raw, METRIC_THRESHOLDS["rework_rate"]),
        "wellbeing": wellbeing_score if wellbeing_score is not None else 0.5,
    }
    return vector


def euclidean_distance(a: dict[str, float], b: dict[str, float]) -> float:
    """Euclidean distance between two normalised vectors."""
    squared_sum = 0.0
    for dim in a:
        squared_sum += (a[dim] - b[dim]) ** 2
    return math.sqrt(squared_sum)


def classify(
    team_vector: dict[str, float],
    has_wellbeing: bool,
) -> tuple[str, float, dict[str, float]]:
    """Classify a team into the closest archetype.

    Args:
        team_vector: Normalised metric vector for the team.
        has_wellbeing: Whether wellbeing survey data was available.

    Returns:
        Tuple of (archetype_name, confidence, distances_to_all_centroids).
    """
    # Calculate distance to each archetype centroid
    distances: dict[str, float] = {}
    for name, definition in ARCHETYPE_DEFINITIONS.items():
        centroid = definition["centroid"]
        dist = euclidean_distance(team_vector, centroid)
        distances[name] = dist

    # Find the closest archetype
    closest = min(distances, key=distances.get)  # type: ignore[arg-type]
    closest_distance = distances[closest]

    # Maximum possible distance in a 6-dimensional 0-1 space is sqrt(6) ≈ 2.449
    max_distance = math.sqrt(6.0)
    raw_confidence = max(0.0, 1.0 - (closest_distance / max_distance))

    # Apply wellbeing cap: without wellbeing data, confidence cannot exceed 0.65
    # See: docs/spec/specification.md §3
    confidence = min(raw_confidence, 0.65) if not has_wellbeing else raw_confidence

    return closest, round(confidence, 2), distances


def identify_bottleneck(
    team_vector: dict[str, float],
    archetype_name: str,
) -> str:
    """Identify the metric dimension where the team is furthest from its centroid.

    Returns a human-readable bottleneck label.

    The bottleneck is the dimension with the largest gap between the team's
    observed value and the archetype centroid, weighted by DORA importance.
    """
    centroid = ARCHETYPE_DEFINITIONS[archetype_name]["centroid"]

    gaps: dict[str, float] = {}
    for dim in ("deployment_frequency", "lead_time", "fdrt", "change_failure_rate", "rework_rate"):
        gap = centroid[dim] - team_vector[dim]
        gaps[dim] = max(0.0, gap)

    if not gaps:
        return "unknown"

    worst_dim = max(gaps, key=gaps.get)  # type: ignore[arg-type]

    # Map dimension names to human-readable labels
    dimension_labels = {
        "deployment_frequency": "deployment_frequency",
        "lead_time": "review_cycle_time",  # lead time maps to review cycle bottleneck
        "fdrt": "recovery_time",
        "change_failure_rate": "change_failure_rate",
        "rework_rate": "rework_rate",
    }

    return dimension_labels.get(worst_dim, worst_dim)


def get_recommendations(archetype_name: str) -> list[str]:
    """Get static recommendations for an archetype."""
    definition = ARCHETYPE_DEFINITIONS.get(archetype_name)
    if definition is None:
        return ["Run a full DORA assessment to identify improvement areas."]
    return definition["recommendations"]


# ═══════════════════════════════════════════════════════════════════════════════
# Database Layer
# ═══════════════════════════════════════════════════════════════════════════════


class ArchetypeDB:
    """Async database access for archetype classification."""

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL")
        if self.dsn is None:
            raise ValueError("DATABASE_URL must be set or dsn argument provided")
        self.pool = None

    async def connect(self):
        import asyncpg

        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=3)

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def get_latest_snapshot(self, team_id: str) -> dict[str, Any] | None:
        """Get the most recent dora_snapshot for a team."""
        query = """
            SELECT
                team_id,
                deployment_frequency,
                lead_time_hours,
                change_failure_rate,
                fdrt_hours,
                rework_rate_pct,
                snapshot_window_start,
                snapshot_window_end,
                recorded_at
            FROM dora_snapshots
            WHERE team_id = $1
            ORDER BY recorded_at DESC
            LIMIT 1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, team_id)
            return dict(row) if row else None

    async def get_wellbeing_scores(
        self,
        team_id: str,
        quarter_start: datetime,
        quarter_end: datetime,
    ) -> list[int]:
        """Get all wellbeing question scores for a team in a quarter.

        The wellbeing_surveys table stores per-respondent scores. We join
        through raw_events or use respondent_id patterns to map to teams.
        For simplicity, we query all surveys submitted in the window and
        return the question scores.

        Returns:
            Flat list of all question scores across all respondents.
        """
        # Map team to surveys — respondents may submit with team context
        # in metadata or through a team_id field. We query by time window.
        query = """
            SELECT q1_score, q2_score, q3_score, q4_score, q5_score
            FROM wellbeing_surveys
            WHERE submitted_at >= $1
              AND submitted_at <= $2
            ORDER BY submitted_at DESC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, quarter_start, quarter_end)

        all_scores: list[int] = []
        for row in rows:
            for col in ("q1_score", "q2_score", "q3_score", "q4_score", "q5_score"):
                all_scores.append(row[col])
        return all_scores

    async def write_classification(
        self,
        team_id: str,
        archetype: str,
        confidence: float,
        snapshot_id: int | None = None,
    ) -> None:
        """Write classification result to archetype_history."""
        # NOTE: The current archetype_history CHECK constraint only allows
        # ('elite', 'high', 'medium', 'low', 'unknown').
        # This constraint needs updating for the 2025 seven-archetype model
        # (Issue #6). Until then, we use a direct INSERT that will work once
        # the constraint is updated, or we would need to ALTER the table.
        #
        # For now, the write will succeed if the constraint is updated to
        # include the seven archetype names. The migration is tracked in:
        #   database/migrations/002-update-archetype-constraint.sql
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO archetype_history
                    (team_id, archetype, confidence, snapshot_id, recorded_at)
                VALUES ($1, $2, $3, $4, NOW())
                """,
                team_id,
                archetype,
                confidence,
                snapshot_id,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Quarter Parsing
# ═══════════════════════════════════════════════════════════════════════════════


def parse_quarter(quarter_str: str) -> tuple[datetime, datetime]:
    """Parse a quarter string like '2026-Q2' into (start, end) datetimes.

    Args:
        quarter_str: Format 'YYYY-QN' where N is 1-4.

    Returns:
        (quarter_start, quarter_end) as timezone-aware datetimes.
    """
    parts = quarter_str.split("-Q")
    if len(parts) != 2:
        raise ValueError(
            f"Invalid quarter format: {quarter_str}. Expected 'YYYY-QN' (e.g. '2026-Q2')"
        )

    year = int(parts[0])
    quarter = int(parts[1])

    month_map = {1: 1, 2: 4, 3: 7, 4: 10}
    start_month = month_map.get(quarter)
    if start_month is None:
        raise ValueError(f"Invalid quarter: {quarter}. Must be 1-4.")

    # Next quarter's start month
    end_month = start_month + 3
    end_year = year
    if end_month > 12:
        end_month = 1
        end_year = year + 1

    start = datetime(year, start_month, 1, tzinfo=UTC)
    end = datetime(end_year, end_month, 1, tzinfo=UTC)
    return start, end


# ═══════════════════════════════════════════════════════════════════════════════
# Main Classification Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════


async def classify_team(
    team_id: str,
    quarter: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Classify a team into a DORA 2025 archetype.

    Args:
        team_id: Repository name (e.g. 'paruff/uFawkesObs').
        quarter: Optional quarter string like '2026-Q2'. Defaults to current quarter.
        verbose: Enable debug logging.

    Returns:
        Classification result dict with archetype, confidence, wellbeing_data
        flag, primary_bottleneck, and recommendations.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    logger.info("Classifying team: %s (quarter: %s)", team_id, quarter or "current")

    # Determine quarter boundaries
    if quarter:
        q_start, q_end = parse_quarter(quarter)
    else:
        now = datetime.now(UTC)
        # Compute current quarter
        current_month = now.month
        q = (current_month - 1) // 3 + 1
        q_start = datetime(now.year, (q - 1) * 3 + 1, 1, tzinfo=UTC)
        q_end = datetime(now.year + 1 if q == 4 else now.year, (q % 4) * 3 + 1, 1, tzinfo=UTC)

    async with ArchetypeDB() as db:
        # Fetch the latest dora_snapshot
        snapshot = await db.get_latest_snapshot(team_id)
        if snapshot is None:
            logger.warning("No DORA metrics found for team: %s", team_id)
            return {
                "archetype": "unknown",
                "confidence": 0.0,
                "wellbeing_data": False,
                "primary_bottleneck": "insufficient_data",
                "recommendations": [
                    "Ensure DORA metrics collection is configured for this team",
                    "Check that the compute-metrics workflow has run",
                ],
            }

        snapshot_id = snapshot.get("id")

        # Fetch wellbeing data
        wellbeing_scores = await db.get_wellbeing_scores(
            team_id=team_id,
            quarter_start=q_start,
            quarter_end=q_end,
        )
        has_wellbeing = len(wellbeing_scores) > 0

        # Normalise wellbeing
        wellbeing_normalised = normalise_wellbeing(wellbeing_scores) if has_wellbeing else None

        logger.debug(
            "Snapshot found for %s: DF=%.2f, LT=%.1f, FDRT=%.1f, CFR=%.3f, RR=%.3f",
            team_id,
            snapshot.get("deployment_frequency", 0),
            snapshot.get("lead_time_hours", 0),
            snapshot.get("fdrt_hours", 0),
            snapshot.get("change_failure_rate", 0),
            snapshot.get("rework_rate_pct", 0),
        )
        logger.debug(
            "Wellbeing data: %s (scores=%d)",
            "available" if has_wellbeing else "NOT available",
            len(wellbeing_scores),
        )

        # Build team vector and classify
        team_vector = build_team_vector(snapshot, wellbeing_normalised)
        archetype_name, confidence, distances = classify(team_vector, has_wellbeing)

        # Identify bottleneck
        bottleneck = identify_bottleneck(team_vector, archetype_name)

        # Get recommendations
        recommendations = get_recommendations(archetype_name)

        # Write to archetype_history
        try:
            await db.write_classification(team_id, archetype_name, confidence, snapshot_id)
            logger.info("Classification written to archetype_history for %s", team_id)
        except Exception as e:
            logger.warning("Failed to write classification: %s", e)
            logger.warning("  (This may be due to the archetype CHECK constraint — see Issue #6)")

        result = {
            "archetype": archetype_name,
            "confidence": confidence,
            "wellbeing_data": has_wellbeing,
            "primary_bottleneck": bottleneck,
            "recommendations": recommendations,
        }

        if verbose:
            result["_debug"] = {
                "team_vector": team_vector,
                "distances": distances,
                "snapshot_recorded_at": str(snapshot.get("recorded_at")),
                "wellbeing_scores_count": len(wellbeing_scores),
            }

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify a team into a DORA 2025 archetype",
    )
    parser.add_argument(
        "--team",
        "-t",
        required=True,
        help="Team/repo name (e.g. paruff/uFawkesObs)",
    )
    parser.add_argument(
        "--quarter",
        "-q",
        default=None,
        help="Quarter string: YYYY-QN (e.g. 2026-Q2). Defaults to current quarter.",
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
        help="Output result as JSON (default: human-readable format)",
    )
    return parser.parse_args(argv)


async def main_async(args: argparse.Namespace) -> None:
    result = await classify_team(
        team_id=args.team,
        quarter=args.quarter,
        verbose=args.verbose,
    )

    if args.json:
        import json

        print(json.dumps(result, indent=2, default=str))
    else:
        _print_result(result)


def _print_result(result: dict[str, Any]) -> None:
    """Pretty-print classification result."""
    print(f"Archetype:          {result['archetype']}")
    print(f"Confidence:         {result['confidence']:.2f}")
    print(f"Wellbeing Data:     {'Yes' if result['wellbeing_data'] else 'No'}")
    print(f"Primary Bottleneck: {result['primary_bottleneck']}")
    print()
    print("Recommendations:")
    for i, rec in enumerate(result.get("recommendations", []), 1):
        print(f"  {i}. {rec}")
    if "_debug" in result:
        print()
        print("[Debug Info]")
        import json

        print(json.dumps(result["_debug"], indent=2, default=str))


def main() -> None:
    """CLI entrypoint."""
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
