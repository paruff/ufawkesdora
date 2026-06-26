"""Unit tests for the DORA seven-archetype classifier.

Tests the core classification logic (normalisation, centroid distance,
archetype assignment, bottleneck identification) in isolation from the
database layer. The DB layer is tested separately in integration tests.

Covers all seven archetypes with representative fixture data, confidence
degradation without wellbeing data, and edge cases.
"""

from datetime import UTC, datetime

import pytest

from compute.archetype import (
    ARCHETYPE_DEFINITIONS,
    ARCHETYPE_ORDER,
    METRIC_THRESHOLDS,
    build_team_vector,
    classify,
    euclidean_distance,
    identify_bottleneck,
    normalise_lower_is_better,
    normalise_metric,
    normalise_wellbeing,
    parse_quarter,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Normalisation Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalisation:
    def test_deployment_frequency_normalisation(self):
        """Higher DF → higher normalised score."""
        low = normalise_metric(1.0, METRIC_THRESHOLDS["deployment_frequency"])
        high = normalise_metric(14.0, METRIC_THRESHOLDS["deployment_frequency"])
        assert low < high
        assert 0 <= low <= 1
        assert 0 <= high <= 1

    def test_deployment_frequency_perfect(self):
        """Very high DF approaches 1.0."""
        score = normalise_metric(100.0, METRIC_THRESHOLDS["deployment_frequency"])
        assert score > 0.85

    def test_deployment_frequency_zero(self):
        """Zero DF gives zero."""
        assert normalise_metric(0.0, METRIC_THRESHOLDS["deployment_frequency"]) == 0.0

    def test_deployment_frequency_none(self):
        """None DF gives zero."""
        assert normalise_metric(None, METRIC_THRESHOLDS["deployment_frequency"]) == 0.0

    def test_lead_time_normalisation(self):
        """Lower LT → higher normalised score."""
        low_lt = normalise_lower_is_better(1.0, METRIC_THRESHOLDS["lead_time"])
        high_lt = normalise_lower_is_better(168.0, METRIC_THRESHOLDS["lead_time"])
        assert low_lt > high_lt
        assert 0 <= low_lt <= 1
        assert high_lt == 0.0  # At threshold = fully bad

    def test_fdrt_normalisation(self):
        """Lower FDRT → higher normalised score."""
        fast = normalise_lower_is_better(0.5, METRIC_THRESHOLDS["fdrt"])
        slow = normalise_lower_is_better(72.0, METRIC_THRESHOLDS["fdrt"])
        assert fast > slow

    def test_cfr_normalisation(self):
        """Lower CFR → higher normalised score."""
        low = normalise_lower_is_better(0.02, METRIC_THRESHOLDS["change_failure_rate"])
        high = normalise_lower_is_better(0.25, METRIC_THRESHOLDS["change_failure_rate"])
        assert low > high

    def test_rework_normalisation(self):
        """Lower Rework → higher normalised score."""
        low = normalise_lower_is_better(0.03, METRIC_THRESHOLDS["rework_rate"])
        high = normalise_lower_is_better(0.20, METRIC_THRESHOLDS["rework_rate"])
        assert low > high

    def test_lower_is_better_none(self):
        """None value gives zero."""
        assert normalise_lower_is_better(None, 10.0) == 0.0

    def test_lower_is_better_zero_threshold(self):
        """Zero threshold means no bad threshold — returns 1.0 (perfect)."""
        assert normalise_lower_is_better(5.0, 0.0) == 1.0


class TestWellbeingNormalisation:
    def test_all_max_scores(self):
        """All 5s → 1.0."""
        assert normalise_wellbeing([5, 5, 5, 5, 5]) == 1.0

    def test_all_min_scores(self):
        """All 1s → 0.2."""
        assert normalise_wellbeing([1, 1, 1, 1, 1]) == 0.2

    def test_mixed_scores(self):
        """Mixed scores produce intermediate values."""
        result = normalise_wellbeing([3, 4, 2, 5, 3])
        assert 0.2 < result < 1.0

    def test_empty_scores(self):
        """Empty list returns 0.0."""
        assert normalise_wellbeing([]) == 0.0

    def test_multiple_respondents(self):
        """Scores are averaged across all questions and respondents."""
        # 2 respondents, each with 5 questions
        scores = [4, 4, 4, 4, 4, 2, 2, 2, 2, 2]
        result = normalise_wellbeing(scores)
        assert result == 0.6  # Average of (4+4+4+4+4+2+2+2+2+2) / (10 * 5) = 30/50 = 0.6


# ═══════════════════════════════════════════════════════════════════════════════
# Vector Building Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildTeamVector:
    def test_builds_all_dimensions(self):
        """Vector contains all six dimensions."""
        snapshot = {
            "deployment_frequency": 10.0,
            "lead_time_hours": 4.0,
            "fdrt_hours": 2.0,
            "change_failure_rate": 0.05,
            "rework_rate_pct": 0.08,
        }
        vector = build_team_vector(snapshot, 0.8)
        assert set(vector.keys()) == {
            "deployment_frequency",
            "lead_time",
            "fdrt",
            "change_failure_rate",
            "rework_rate",
            "wellbeing",
        }

    def test_vector_values_in_range(self):
        """All vector values are between 0 and 1."""
        snapshot = {
            "deployment_frequency": 5.0,
            "lead_time_hours": 24.0,
            "fdrt_hours": 12.0,
            "change_failure_rate": 0.10,
            "rework_rate_pct": 0.12,
        }
        vector = build_team_vector(snapshot, 0.6)
        for dim, val in vector.items():
            assert 0.0 <= val <= 1.0, f"Dimension {dim} out of range: {val}"

    def test_no_wellbeing_defaults_to_0_5(self):
        """Without wellbeing data, the wellbeing dimension defaults to 0.5 (neutral prior)."""
        snapshot = {
            "deployment_frequency": 5.0,
            "lead_time_hours": 24.0,
            "fdrt_hours": 12.0,
            "change_failure_rate": 0.10,
            "rework_rate_pct": 0.12,
        }
        vector = build_team_vector(snapshot, None)
        assert vector["wellbeing"] == 0.5

    def test_null_metrics_default_to_zero(self):
        """Null metrics in the snapshot default to 0."""
        snapshot = {
            "deployment_frequency": 5.0,
            "lead_time_hours": None,
            "fdrt_hours": None,
            "change_failure_rate": 0.10,
            "rework_rate_pct": None,
        }
        vector = build_team_vector(snapshot, 0.7)
        assert vector["lead_time"] == 0.0
        assert vector["fdrt"] == 0.0
        assert vector["rework_rate"] == 0.0
        assert vector["deployment_frequency"] > 0.0  # Still has a value


# ═══════════════════════════════════════════════════════════════════════════════
# Classification Tests
# ═══════════════════════════════════════════════════════════════════════════════
# Each test simulates a team whose metrics match a specific archetype centroid.
# The classifier should assign them to the correct archetype.
#
# Fixture data approximates the centroid signatures from ARCHETYPE_DEFINITIONS.


@pytest.fixture
def harmonious_team():
    """High throughput + low instability + high wellbeing."""
    snapshot = {
        "deployment_frequency": 12.0,  # Very high
        "lead_time_hours": 2.0,  # Very fast
        "fdrt_hours": 1.0,  # Fast recovery
        "change_failure_rate": 0.03,  # Low failure rate
        "rework_rate_pct": 0.04,  # Low rework
    }
    return snapshot, 0.85  # High wellbeing


@pytest.fixture
def pragmatic_team():
    """High speed/stability + lower engagement."""
    snapshot = {
        "deployment_frequency": 10.0,  # High
        "lead_time_hours": 4.0,  # Fast
        "fdrt_hours": 6.0,  # Moderate recovery
        "change_failure_rate": 0.05,  # Low failure rate
        "rework_rate_pct": 0.10,  # Moderate rework
    }
    return snapshot, 0.45  # Lower wellbeing


@pytest.fixture
def stable_team():
    """High quality + sustainable pace + lower throughput."""
    snapshot = {
        "deployment_frequency": 3.0,  # Moderate throughput
        "lead_time_hours": 24.0,  # Moderate speed
        "fdrt_hours": 2.0,  # Good recovery
        "change_failure_rate": 0.02,  # Very low failure rate
        "rework_rate_pct": 0.03,  # Low rework
    }
    return snapshot, 0.70  # Moderate-good wellbeing


@pytest.fixture
def constrained_team():
    """Stable systems + process overhead."""
    snapshot = {
        "deployment_frequency": 2.0,  # Below-average throughput
        "lead_time_hours": 96.0,  # Slow (process overhead)
        "fdrt_hours": 12.0,  # Moderate recovery
        "change_failure_rate": 0.08,  # Moderate-low failure rate (stable systems)
        "rework_rate_pct": 0.12,  # Moderate rework
    }
    return snapshot, 0.40  # Below-average wellbeing


@pytest.fixture
def legacy_team():
    """Reactive, unstable systems + low morale."""
    snapshot = {
        "deployment_frequency": 0.5,  # Very low
        "lead_time_hours": 120.0,  # Very slow
        "fdrt_hours": 96.0,  # Slow recovery
        "change_failure_rate": 0.25,  # High failure rate
        "rework_rate_pct": 0.22,  # High rework
    }
    return snapshot, 0.25  # Low wellbeing


@pytest.fixture
def high_impact_team():
    """High-value, low cadence, high instability."""
    snapshot = {
        "deployment_frequency": 1.0,  # Low throughput
        "lead_time_hours": 48.0,  # Slow delivery
        "fdrt_hours": 72.0,  # Slow recovery
        "change_failure_rate": 0.18,  # High failure rate
        "rework_rate_pct": 0.14,  # Moderate-high rework
    }
    return snapshot, 0.55  # Moderate wellbeing


class TestClassify:
    def test_harmonious_high_achievers(self, harmonious_team):
        """Team matching Harmonious signature is classified correctly."""
        snapshot, wellbeing_score = harmonious_team
        vector = build_team_vector(snapshot, wellbeing_score)
        archetype, confidence, distances = classify(vector, has_wellbeing=True)
        assert archetype == "Harmonious high-achievers"
        assert confidence >= 0.70  # High confidence with wellbeing data

    def test_pragmatic_performers(self, pragmatic_team):
        """Team matching Pragmatic signature is classified correctly."""
        snapshot, wellbeing_score = pragmatic_team
        vector = build_team_vector(snapshot, wellbeing_score)
        archetype, confidence, distances = classify(vector, has_wellbeing=True)
        assert archetype == "Pragmatic performers"
        assert confidence >= 0.50

    def test_stable_and_methodical(self, stable_team):
        """Team matching Stable signature is classified correctly."""
        snapshot, wellbeing_score = stable_team
        vector = build_team_vector(snapshot, wellbeing_score)
        archetype, confidence, distances = classify(vector, has_wellbeing=True)
        assert archetype == "Stable and methodical"
        assert confidence >= 0.65

    def test_constrained_by_process(self, constrained_team):
        """Team matching Constrained signature is classified correctly."""
        snapshot, wellbeing_score = constrained_team
        vector = build_team_vector(snapshot, wellbeing_score)
        archetype, confidence, distances = classify(vector, has_wellbeing=True)
        assert archetype == "Constrained by process"
        assert confidence >= 0.45

    def test_legacy_bottleneck(self, legacy_team):
        """Team matching Legacy signature is classified correctly."""
        snapshot, wellbeing_score = legacy_team
        vector = build_team_vector(snapshot, wellbeing_score)
        archetype, confidence, distances = classify(vector, has_wellbeing=True)
        assert archetype == "Legacy bottleneck"
        assert confidence >= 0.55

    def test_high_impact_low_cadence(self, high_impact_team):
        """Team matching High Impact signature is classified correctly."""
        snapshot, wellbeing_score = high_impact_team
        vector = build_team_vector(snapshot, wellbeing_score)
        archetype, confidence, distances = classify(vector, has_wellbeing=True)
        assert archetype == "High impact, low cadence"
        assert confidence >= 0.45

    def test_confidence_capped_without_wellbeing(self, harmonious_team):
        """Without wellbeing data, confidence is capped at 0.65."""
        snapshot, _ = harmonious_team
        vector = build_team_vector(snapshot, None)  # No wellbeing
        archetype, confidence, distances = classify(vector, has_wellbeing=False)
        assert confidence <= 0.65

    def test_confidence_higher_with_wellbeing(self, harmonious_team):
        """Same team with wellbeing data gets higher confidence."""
        snapshot, _ = harmonious_team
        vector_no_wb = build_team_vector(snapshot, None)
        vector_wb = build_team_vector(snapshot, 0.9)

        _, conf_no_wb, _ = classify(vector_no_wb, has_wellbeing=False)
        _, conf_wb, _ = classify(vector_wb, has_wellbeing=True)

        assert conf_wb > conf_no_wb

    def test_near_perfect_team_gets_high_confidence(self):
        """A team with perfect metrics in all dimensions gets high confidence."""
        snapshot = {
            "deployment_frequency": 50.0,
            "lead_time_hours": 0.5,
            "fdrt_hours": 0.25,
            "change_failure_rate": 0.01,
            "rework_rate_pct": 0.01,
        }
        vector = build_team_vector(snapshot, 1.0)
        _, confidence, distances = classify(vector, has_wellbeing=True)
        assert confidence >= 0.80

    def test_returns_distance_to_all_centroids(self):
        """Distances dict contains all archetypes."""
        snapshot = {
            "deployment_frequency": 5.0,
            "lead_time_hours": 24.0,
            "fdrt_hours": 12.0,
            "change_failure_rate": 0.10,
            "rework_rate_pct": 0.12,
        }
        vector = build_team_vector(snapshot, 0.6)
        _, _, distances = classify(vector, has_wellbeing=True)
        for name in ARCHETYPE_ORDER:
            assert name in distances
            assert distances[name] >= 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Bottleneck Identification Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBottleneckIdentification:
    def test_bottleneck_is_worst_dimension(self):
        """Bottleneck identifies the dimension with largest centroid gap."""
        # A team with very low deployment_frequency
        snapshot = {
            "deployment_frequency": 0.2,
            "lead_time_hours": 2.0,
            "fdrt_hours": 1.0,
            "change_failure_rate": 0.03,
            "rework_rate_pct": 0.04,
        }
        vector = build_team_vector(snapshot, 0.8)
        bottleneck = identify_bottleneck(vector, "Harmonious high-achievers")
        assert bottleneck == "deployment_frequency"

    def test_bottleneck_lead_time(self):
        """High lead time maps to review_cycle_time bottleneck."""
        snapshot = {
            "deployment_frequency": 5.0,
            "lead_time_hours": 168.0,  # Very slow
            "fdrt_hours": 2.0,
            "change_failure_rate": 0.05,
            "rework_rate_pct": 0.06,
        }
        vector = build_team_vector(snapshot, 0.7)
        bottleneck = identify_bottleneck(vector, "Pragmatic performers")
        assert bottleneck == "review_cycle_time"


# ═══════════════════════════════════════════════════════════════════════════════
# Euclidian Distance Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestEuclideanDistance:
    def test_identical_vectors_have_zero_distance(self):
        """Same points have distance 0."""
        v = {"a": 1.0, "b": 0.5, "c": 0.0}
        assert euclidean_distance(v, v) == 0.0

    def test_opposite_vectors_have_maximum_distance(self):
        """Opposite corners have near-max distance."""
        v1 = {"a": 0.0, "b": 0.0, "c": 0.0}
        v2 = {"a": 1.0, "b": 1.0, "c": 1.0}
        import math

        assert euclidean_distance(v1, v2) == pytest.approx(math.sqrt(3.0))


# ═══════════════════════════════════════════════════════════════════════════════
# Quarter Parsing Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseQuarter:
    def test_q1(self):
        start, end = parse_quarter("2026-Q1")
        assert start == datetime(2026, 1, 1, tzinfo=UTC)
        assert end == datetime(2026, 4, 1, tzinfo=UTC)

    def test_q2(self):
        start, end = parse_quarter("2026-Q2")
        assert start == datetime(2026, 4, 1, tzinfo=UTC)
        assert end == datetime(2026, 7, 1, tzinfo=UTC)

    def test_q3(self):
        start, end = parse_quarter("2026-Q3")
        assert start == datetime(2026, 7, 1, tzinfo=UTC)
        assert end == datetime(2026, 10, 1, tzinfo=UTC)

    def test_q4_wraps_year(self):
        """Q4 end rolls over to next year."""
        start, end = parse_quarter("2026-Q4")
        assert start == datetime(2026, 10, 1, tzinfo=UTC)
        assert end == datetime(2027, 1, 1, tzinfo=UTC)

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid quarter format"):
            parse_quarter("2026-X2")

    def test_invalid_quarter_number(self):
        with pytest.raises(ValueError, match="Invalid quarter"):
            parse_quarter("2026-Q5")


# ═══════════════════════════════════════════════════════════════════════════════
# Archetype Definitions Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestArchetypeDefinitions:
    def test_all_archetypes_have_required_fields(self):
        """Every archetype definition has centroid, description, recommendations."""
        for name, defn in ARCHETYPE_DEFINITIONS.items():
            assert "centroid" in defn, f"{name} missing centroid"
            assert "description" in defn, f"{name} missing description"
            assert "recommendations" in defn, f"{name} missing recommendations"
            assert len(defn["recommendations"]) >= 2, f"{name} has fewer than 2 recommendations"

    def test_all_centroids_have_all_dimensions(self):
        """Every centroid has all 6 dimensions with 0-1 values."""
        dimensions = {
            "deployment_frequency",
            "lead_time",
            "fdrt",
            "change_failure_rate",
            "rework_rate",
            "wellbeing",
        }
        for name, defn in ARCHETYPE_DEFINITIONS.items():
            centroid = defn["centroid"]
            assert set(centroid.keys()) == dimensions, (
                f"{name} missing dimensions: {dimensions - set(centroid.keys())}"
            )
            for dim, val in centroid.items():
                assert 0.0 <= val <= 1.0, f"{name}.{dim} out of range: {val}"

    def test_no_duplicate_centroids(self):
        """All centroids are distinct (no two archetypes share the same centroid)."""
        centroids = [
            tuple(sorted(defn["centroid"].items())) for defn in ARCHETYPE_DEFINITIONS.values()
        ]
        assert len(centroids) == len(set(centroids)), "Duplicate centroids detected"

    def test_archetype_order_contains_all(self):
        """ARCHETYPE_ORDER lists all defined archetypes."""
        assert set(ARCHETYPE_ORDER) == set(ARCHETYPE_DEFINITIONS.keys())
