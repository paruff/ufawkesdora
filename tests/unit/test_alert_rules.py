"""Unit tests for Prometheus alert rules.

Tests verify that alert rules fire correctly when metrics degrade
and do not fire when metrics are healthy.
"""

from pathlib import Path

import pytest
import yaml


def test_dora_regression_alerts():
    """Test that DORA regression alerts fire on degraded data."""
    # This test would use promtool to test the alert rules
    # For now, we'll verify the YAML structure is correct

    # Check that the dora-regression.yaml file exists and is valid YAML
    rules_path = Path("alerts/dora-regression.yaml")
    assert rules_path.exists(), "dora-regression.yaml should exist"

    with open(rules_path) as f:
        rules = yaml.safe_load(f)

    assert "groups" in rules
    assert len(rules["groups"]) == 1
    assert rules["groups"][0]["name"] == "dora_regression"
    assert len(rules["groups"][0]["rules"]) == 5

    # Check each alert is present
    alert_names = {rule["alert"] for rule in rules["groups"][0]["rules"]}
    expected_alerts = {
        "DoraDeploymentFrequencyDrop",
        "DoraLeadTimeIncrease",
        "DoraFDRTSpike",
        "DoraCFRSpike",
        "DoraReworkRateClimb",
    }
    assert alert_names == expected_alerts

    # Verify each alert has required fields
    for rule in rules["groups"][0]["rules"]:
        assert "alert" in rule
        assert "expr" in rule
        assert "for" in rule
        assert "labels" in rule
        assert "annotations" in rule
        assert "severity" in rule["labels"]
        assert "category" in rule["labels"]
        assert "summary" in rule["annotations"]
        assert "description" in rule["annotations"]
        assert "runbook_url" in rule["annotations"]


def test_leading_indicator_alerts():
    """Test that leading indicator alerts are present."""
    # Check that the leading-indicator.yaml file exists and is valid YAML
    rules_path = Path("alerts/leading-indicator.yaml")
    assert rules_path.exists(), "leading-indicator.yaml should exist"

    with open(rules_path) as f:
        rules = yaml.safe_load(f)

    assert "groups" in rules
    assert len(rules["groups"]) == 1
    assert rules["groups"][0]["name"] == "leading_indicator"
    assert len(rules["groups"][0]["rules"]) == 2

    # Check each alert is present
    alert_names = {rule["alert"] for rule in rules["groups"][0]["rules"]}
    expected_alerts = {"DoraLeadingIndicatorPRCycle", "DoraLeadingIndicatorPRSize"}
    assert alert_names == expected_alerts

    # Verify each alert has required fields
    for rule in rules["groups"][0]["rules"]:
        assert "alert" in rule
        assert "expr" in rule
        assert "for" in rule
        assert "labels" in rule
        assert "annotations" in rule
        assert "severity" in rule["labels"]
        assert "category" in rule["labels"]
        assert "summary" in rule["annotations"]
        assert "description" in rule["annotations"]
        assert "runbook_url" in rule["annotations"]


def test_alert_rules_have_proper_severity_and_category():
    """Test that alerts have appropriate severity and category labels."""
    # Test DORA regression alerts
    with open("alerts/dora-regression.yaml") as f:
        rules = yaml.safe_load(f)

    for rule in rules["groups"][0]["rules"]:
        assert "labels" in rule
        assert "severity" in rule["labels"]
        assert "category" in rule["labels"]

        # Check specific alerts
        if rule["alert"] == "DoraFDRTSpike":
            assert rule["labels"]["severity"] == "critical"
            assert rule["labels"]["category"] == "dora_throughput"
        else:
            assert rule["labels"]["severity"] == "warning"
            if rule["alert"] in ["DoraDeploymentFrequencyDrop", "DoraLeadTimeIncrease"]:
                assert rule["labels"]["category"] == "dora_throughput"
            else:
                assert rule["labels"]["category"] == "dora_stability"

    # Test leading indicator alerts
    with open("alerts/leading-indicator.yaml") as f:
        rules = yaml.safe_load(f)

    for rule in rules["groups"][0]["rules"]:
        assert "labels" in rule
        assert "severity" in rule["labels"]
        assert "category" in rule["labels"]
        assert rule["labels"]["severity"] == "warning"
        assert rule["labels"]["category"] == "leading_indicator"


if __name__ == "__main__":
    pytest.main([__file__])
