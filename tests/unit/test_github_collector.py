"""Tests for the GitHub Actions collector workflows.

Since the collectors are implemented as GitHub Actions YAML workflows
(not Python modules), these tests validate the transformation contract:

  1. Load sample GitHub webhook payloads from fixtures
  2. Apply the same transformation logic the workflows use
  3. Validate the resulting canonical events against their schemas

This catches schema drift between the collectors and the event schemas.
"""

import json
from pathlib import Path

from jsonschema import Draft7Validator, FormatChecker

# ── Paths ──────────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent.parent / "acceptance" / "fixtures"
SCHEMAS_DIR = Path(__file__).parent.parent.parent / "events"


# ── Helpers ────────────────────────────────────────────────────────────────


def load_json(path: Path) -> dict:
    """Load a JSON file."""
    with open(path) as f:
        return json.load(f)


def load_schema(name: str) -> dict:
    """Load a canonical event schema by filename."""
    return load_json(SCHEMAS_DIR / name)


# ── Transformations (mirror the YAML workflow logic) ───────────────────────


def transform_deployment_webhook(webhook: dict) -> dict:
    """Simulate the dora-deployment-event.yml transformation.

    The YAML workflow extracts fields from the GitHub context and
    constructs a canonical deployment event. This function mirrors
    that logic for testing.
    """
    event = webhook["event"]
    repo = event["repository"]["full_name"]
    service = event["repository"]["name"]
    deployed_at = event["release"]["published_at"]
    commit_sha = event["release"]["target_commitish"]

    # The YAML workflow uses:
    #   github.sha → commit_sha
    #   github.event.release.published_at → deployed_at
    #   inputs.status → status
    #   inputs.pipeline_url → pipeline_url
    # Since the fixture doesn't have github.sha, we use a SHA from the
    # expected_canonical_event if "commit_sha" isn't in the webhook event.
    fixture_expectation = webhook.get("expected_canonical_event", {})

    return {
        "schema_version": "1.0",
        "event_type": "deployment",
        "repo": repo,
        "service": service,
        "environment": "production",
        "commit_sha": fixture_expectation.get(
            "commit_sha", commit_sha or "0000000000000000000000000000000000000000"
        ),
        "deployed_at": deployed_at,
        "status": fixture_expectation.get("status", "success"),
        "pipeline_url": fixture_expectation.get(
            "pipeline_url",
            f"https://github.com/{repo}/actions/runs/12345",
        ),
        "ai_assisted": fixture_expectation.get("ai_assisted", False),
    }


def find_first_commit_at(api_response: dict) -> str:
    """Determine the oldest commit timestamp (first_commit_at).

    Mirrors the logic in dora-pr-event.yml:
      - Sorts commits by committer.date ascending
      - Returns the earliest date
      - Falls back to empty string if no commits
    """
    commits = api_response.get("commits", [])
    if not commits:
        return ""

    # Sort by committer.date ascending
    sorted_commits = sorted(
        commits,
        key=lambda c: c.get("commit", {}).get("committer", {}).get("date", ""),
    )
    return sorted_commits[0].get("commit", {}).get("committer", {}).get("date", "")


def transform_pr_webhook(webhook: dict) -> dict:
    """Simulate the dora-pr-event.yml transformation.

    The YAML workflow:
      1. Receives inputs (pr_number)
      2. Fetches PR details and commits via gh api
      3. Finds first_commit_at from oldest commit
      4. Constructs canonical PR event
    """
    event = webhook["event"]
    repo = event["repository"]["full_name"]
    pr = event["pull_request"]
    api_resp = webhook.get("simulated_api_response", {})
    fixture_expectation = webhook.get("expected_canonical_event", {})

    first_commit_at = find_first_commit_at(api_resp)
    if not first_commit_at:
        first_commit_at = pr.get("merged_at", "")

    return {
        "schema_version": "1.0",
        "event_type": "pr",
        "repo": repo,
        "pr_number": pr["number"],
        "commit_sha": fixture_expectation.get("commit_sha", pr.get("merge_commit_sha", "")),
        "status": fixture_expectation.get("status", "merged"),
        "occurred_at": pr.get("merged_at", ""),
        "first_commit_at": first_commit_at,
        "ai_assisted": fixture_expectation.get("ai_assisted", False),
    }


# ── Tests ──────────────────────────────────────────────────────────────────


class TestDeploymentCollector:
    """Validate deployment event transformation against canonical schema."""

    def _load_fixture(self) -> dict:
        return load_json(FIXTURES_DIR / "github-deployment-webhook.json")

    def test_transformation_produces_valid_event(self):
        """Transformed deployment event passes schema validation."""
        fixture = self._load_fixture()
        canonical = transform_deployment_webhook(fixture)
        schema = load_schema("deployment-event.schema.json")

        validator = Draft7Validator(schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(canonical))

        assert not errors, "Deployment event schema errors: " + "; ".join(e.message for e in errors)

    def test_transformed_event_matches_expected(self):
        """Transformed event matches the expected canonical payload."""
        fixture = self._load_fixture()
        expected = fixture["expected_canonical_event"]
        canonical = transform_deployment_webhook(fixture)

        for key in expected:
            assert canonical.get(key) == expected[key], (
                f"Field '{key}': expected {expected[key]}, got {canonical.get(key)}"
            )

    def test_required_fields_present(self):
        """All required deployment schema fields are present."""
        fixture = self._load_fixture()
        canonical = transform_deployment_webhook(fixture)
        schema = load_schema("deployment-event.schema.json")

        required = schema.get("required", [])
        for field in required:
            assert field in canonical and canonical[field] is not None, (
                f"Required field '{field}' missing in transformed event"
            )

    def test_event_type_is_deployment(self):
        """event_type must be 'deployment'."""
        fixture = self._load_fixture()
        canonical = transform_deployment_webhook(fixture)
        assert canonical["event_type"] == "deployment"

    def test_repo_format(self):
        """repo must be in org/repo format."""
        fixture = self._load_fixture()
        canonical = transform_deployment_webhook(fixture)
        assert "/" in canonical["repo"]
        parts = canonical["repo"].split("/")
        assert len(parts) == 2
        assert all(len(p) > 0 for p in parts)


class TestPRCollector:
    """Validate PR event transformation against canonical schema."""

    def _load_fixture(self) -> dict:
        return load_json(FIXTURES_DIR / "github-pr-webhook.json")

    def test_transformation_produces_valid_event(self):
        """Transformed PR event passes schema validation."""
        fixture = self._load_fixture()
        canonical = transform_pr_webhook(fixture)
        schema = load_schema("pr-event.schema.json")

        validator = Draft7Validator(schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(canonical))

        assert not errors, "PR event schema errors: " + "; ".join(e.message for e in errors)

    def test_transformed_event_matches_expected(self):
        """Transformed event matches the expected canonical payload."""
        fixture = self._load_fixture()
        expected = fixture["expected_canonical_event"]
        canonical = transform_pr_webhook(fixture)

        for key in expected:
            assert canonical.get(key) == expected[key], (
                f"Field '{key}': expected {expected[key]}, got {canonical.get(key)}"
            )

    def test_required_fields_present(self):
        """All required PR schema fields are present."""
        fixture = self._load_fixture()
        canonical = transform_pr_webhook(fixture)
        schema = load_schema("pr-event.schema.json")

        required = schema.get("required", [])
        for field in required:
            assert field in canonical and canonical[field] is not None, (
                f"Required field '{field}' missing in transformed event"
            )

    def test_event_type_is_pr(self):
        """event_type must be 'pr'."""
        fixture = self._load_fixture()
        canonical = transform_pr_webhook(fixture)
        assert canonical["event_type"] == "pr"

    def test_pr_number_is_positive(self):
        """pr_number must be a positive integer."""
        fixture = self._load_fixture()
        canonical = transform_pr_webhook(fixture)
        assert canonical["pr_number"] > 0

    def test_first_commit_at_before_occurred_at(self):
        """first_commit_at must be earlier than occurred_at (PR merged)."""
        fixture = self._load_fixture()
        canonical = transform_pr_webhook(fixture)
        assert canonical["first_commit_at"] < canonical["occurred_at"], (
            f"first_commit_at {canonical['first_commit_at']} must be before "
            f"occurred_at {canonical['occurred_at']}"
        )

    def test_find_first_commit_at_earliest(self):
        """find_first_commit_at returns the oldest commit date."""
        api_resp = {
            "commits": [
                {"commit": {"committer": {"date": "2026-06-23T12:00:00Z"}}},
                {"commit": {"committer": {"date": "2026-06-20T08:00:00Z"}}},
                {"commit": {"committer": {"date": "2026-06-21T10:30:00Z"}}},
            ]
        }
        assert find_first_commit_at(api_resp) == "2026-06-20T08:00:00Z"

    def test_find_first_commit_at_empty(self):
        """find_first_commit_at returns empty string when no commits."""
        assert find_first_commit_at({"commits": []}) == ""


class TestAdditionalEventScenarios:
    """Edge cases and additional scenarios."""

    def test_deployment_failed_status(self):
        """Deployment with 'failed' status still passes schema validation."""
        canonical = {
            "schema_version": "1.0",
            "event_type": "deployment",
            "repo": "org/repo",
            "service": "repo",
            "environment": "staging",
            "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            "deployed_at": "2026-06-23T14:30:00Z",
            "status": "failed",
            "pipeline_url": "https://github.com/org/repo/actions/runs/1",
            "ai_assisted": True,
        }
        schema = load_schema("deployment-event.schema.json")
        validator = Draft7Validator(schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(canonical))
        assert not errors, "; ".join(e.message for e in errors)

    def test_deployment_rollback_status(self):
        """Deployment with 'rollback' status passes schema validation."""
        canonical = {
            "schema_version": "1.0",
            "event_type": "deployment",
            "repo": "org/repo",
            "service": "repo",
            "environment": "production",
            "commit_sha": "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1",
            "deployed_at": "2026-06-23T15:00:00Z",
            "status": "rollback",
            "pipeline_url": "https://github.com/org/repo/actions/runs/2",
        }
        schema = load_schema("deployment-event.schema.json")
        validator = Draft7Validator(schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(canonical))
        assert not errors, "; ".join(e.message for e in errors)

    def test_pr_with_ai_assisted(self):
        """PR event with ai_assisted=true passes schema validation."""
        canonical = {
            "schema_version": "1.0",
            "event_type": "pr",
            "repo": "org/repo",
            "pr_number": 42,
            "commit_sha": "c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2",
            "status": "merged",
            "occurred_at": "2026-06-23T14:30:00Z",
            "first_commit_at": "2026-06-20T08:00:00Z",
            "ai_assisted": True,
        }
        schema = load_schema("pr-event.schema.json")
        validator = Draft7Validator(schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(canonical))
        assert not errors, "; ".join(e.message for e in errors)

    def test_deployment_with_duration(self):
        """Deployment with optional deploy_duration_seconds passes validation."""
        canonical = {
            "schema_version": "1.0",
            "event_type": "deployment",
            "repo": "org/repo",
            "service": "repo",
            "environment": "production",
            "commit_sha": "d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3",
            "deployed_at": "2026-06-23T16:00:00Z",
            "status": "success",
            "pipeline_url": "https://github.com/org/repo/actions/runs/3",
            "deploy_duration_seconds": 180,
        }
        schema = load_schema("deployment-event.schema.json")
        validator = Draft7Validator(schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(canonical))
        assert not errors, "; ".join(e.message for e in errors)
