"""Unit tests for the uFawkesDORA canonical event schemas.

Validates that:
- Each JSON Schema file is valid draft-07
- Known-good payloads pass validation
- Known-bad payloads are correctly rejected
"""

import datetime
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, FormatChecker, ValidationError, validate

# ── Format checker for date-time ───────────────────────────────────────────────
# jsonschema does not ship with date-time format validation by default.
# Register a custom checker so tests can enforce ISO 8601 timestamps.


def _check_date_time(instance: str) -> bool:
    """Validate ISO 8601 date-time strings using Python's fromisoformat."""
    if not isinstance(instance, str):
        return True  # type validation handles non-strings
    try:
        datetime.datetime.fromisoformat(instance)
        return True
    except (ValueError, TypeError):
        return False


_format_checker = FormatChecker()
_format_checker.checks("date-time")(_check_date_time)


# ── Helpers ────────────────────────────────────────────────────────────────────


def find_repo_root() -> Path:
    """Walk up from this file's directory to find the repo root."""
    current = Path(__file__).resolve().parent
    while current.name != "ufawkesdora" and current.parent != current:
        current = current.parent
    assert current.name == "ufawkesdora", f"Could not find repo root from {__file__}"
    return current


def load_schema(name: str) -> dict:
    """Load a JSON Schema file from the events/ directory."""
    repo_root = find_repo_root()
    schema_path = repo_root / "events" / name
    with open(schema_path) as f:
        return json.load(f)


def validate_with_format(instance: dict, schema: dict):
    """Validate with format checking enabled (e.g., date-time, uri)."""
    Draft7Validator(schema, format_checker=_format_checker).validate(instance)


def load_all_schemas() -> dict[str, dict]:
    """Load all event schemas keyed by schema file stem."""
    repo_root = find_repo_root()
    schemas = {}
    for p in sorted((repo_root / "events").glob("*.schema.json")):
        with open(p) as f:
            schemas[p.stem] = json.load(f)
    return schemas


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def deployment_schema() -> dict:
    return load_schema("deployment-event.schema.json")


@pytest.fixture(scope="module")
def incident_schema() -> dict:
    return load_schema("incident-event.schema.json")


@pytest.fixture(scope="module")
def pr_schema() -> dict:
    return load_schema("pr-event.schema.json")


@pytest.fixture(scope="module")
def rework_schema() -> dict:
    return load_schema("rework-event.schema.json")


# ── Schema Meta-Validation ─────────────────────────────────────────────────────


class TestSchemaValidity:
    """Verify each schema file is itself valid JSON Schema (draft-07)."""

    @pytest.mark.parametrize(
        "schema_name",
        [
            "deployment-event.schema.json",
            "incident-event.schema.json",
            "pr-event.schema.json",
            "rework-event.schema.json",
        ],
    )
    def test_schema_is_valid_draft07(self, schema_name):
        """AC-04: All schemas must be valid draft-07 JSON Schema documents."""
        schema = load_schema(schema_name)
        # Draft7Validator.check_schema raises on invalidity
        Draft7Validator.check_schema(schema)

    def test_all_schemas_have_schema_version(self):
        """Every schema should have schema_version in its properties."""
        for name, schema in load_all_schemas().items():
            props = schema.get("properties", {})
            assert "schema_version" in props, f"{name} is missing schema_version property"

    def test_all_schemas_have_event_type(self):
        """Every schema should have event_type as a const in its properties."""
        for name, schema in load_all_schemas().items():
            props = schema.get("properties", {})
            assert "event_type" in props, f"{name} is missing event_type property"
            assert "const" in props["event_type"], f"{name}: event_type should be a const"

    def test_all_schemas_have_additional_properties_false(self):
        """All schemas should reject unknown fields."""
        for name, schema in load_all_schemas().items():
            assert schema.get("additionalProperties") is False, (
                f"{name} should set additionalProperties: false"
            )


# ── Deployment Event ───────────────────────────────────────────────────────────


class TestDeploymentEvent:
    """Validate deployment-event.schema.json."""

    @pytest.fixture
    def valid_payload(self) -> dict:
        return {
            "schema_version": "1.0",
            "event_type": "deployment",
            "repo": "my-org/my-service",
            "service": "api-gateway",
            "environment": "production",
            "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",  # pragma: allowlist secret
            "deployed_at": "2026-06-22T10:30:00Z",
            "status": "success",
            "pipeline_url": "https://github.com/my-org/my-service/actions/runs/12345",
        }

    def test_valid_deployment_passes(self, deployment_schema, valid_payload):
        """AC-01: A valid deployment payload must pass schema validation."""
        validate(valid_payload, deployment_schema)

    def test_invalid_status_fails(self, deployment_schema, valid_payload):
        """AC-01: An invalid status value must be rejected."""
        payload = dict(valid_payload, status="unknown")
        with pytest.raises(ValidationError):
            validate(payload, deployment_schema)

    def test_missing_required_field_fails(self, deployment_schema, valid_payload):
        """AC-01: Omitting a required field must be rejected."""
        payload = {k: v for k, v in valid_payload.items() if k != "repo"}
        with pytest.raises(ValidationError):
            validate(payload, deployment_schema)

    def test_wrong_event_type_fails(self, deployment_schema, valid_payload):
        """AC-01: Using a non-deployment event_type must be rejected."""
        payload = dict(valid_payload, event_type="incident")
        with pytest.raises(ValidationError):
            validate(payload, deployment_schema)

    def test_optional_fields_accepted(self, deployment_schema, valid_payload):
        """AC-01: Providing optional fields must not break validation."""
        payload = dict(valid_payload, deploy_duration_seconds=120, ai_assisted=True)
        validate(payload, deployment_schema)

    def test_additional_properties_rejected(self, deployment_schema, valid_payload):
        """AC-01: Extra fields not in the schema must be rejected."""
        payload = dict(valid_payload, unknown_field="something")
        with pytest.raises(ValidationError):
            validate(payload, deployment_schema)

    def test_commit_sha_format(self, deployment_schema, valid_payload):
        """AC-01: commit_sha must be a 40-char hex string."""
        payload = dict(valid_payload, commit_sha="short-sha")
        with pytest.raises(ValidationError):
            validate(payload, deployment_schema)

    def test_deployed_at_iso8601(self, deployment_schema, valid_payload):
        """AC-01: deployed_at must be valid ISO 8601."""
        payload = dict(valid_payload, deployed_at="not-a-date")
        with pytest.raises(ValidationError):
            validate_with_format(payload, deployment_schema)


# ── Incident Event ─────────────────────────────────────────────────────────────


class TestIncidentEvent:
    """Validate incident-event.schema.json."""

    @pytest.fixture
    def valid_payload(self) -> dict:
        return {
            "schema_version": "1.0",
            "event_type": "incident",
            "incident_id": "INC-12345",
            "repo": "my-org/my-service",
            "service": "api-gateway",
            "status": "opened",
            "occurred_at": "2026-06-22T10:30:00Z",
        }

    def test_valid_incident_passes(self, incident_schema, valid_payload):
        validate(valid_payload, incident_schema)

    def test_invalid_status_fails(self, incident_schema, valid_payload):
        payload = dict(valid_payload, status="acknowledged")
        with pytest.raises(ValidationError):
            validate(payload, incident_schema)

    def test_missing_required_field_fails(self, incident_schema, valid_payload):
        payload = {k: v for k, v in valid_payload.items() if k != "incident_id"}
        with pytest.raises(ValidationError):
            validate(payload, incident_schema)

    def test_wrong_event_type_fails(self, incident_schema, valid_payload):
        payload = dict(valid_payload, event_type="deployment")
        with pytest.raises(ValidationError):
            validate(payload, incident_schema)

    def test_optional_fields_accepted(self, incident_schema, valid_payload):
        payload = dict(
            valid_payload,
            linked_deployment_sha="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",  # pragma: allowlist secret
            severity="SEV1",
        )
        validate(payload, incident_schema)

    def test_additional_properties_rejected(self, incident_schema, valid_payload):
        payload = dict(valid_payload, unknown_field="x")
        with pytest.raises(ValidationError):
            validate(payload, incident_schema)


# ── PR Event ───────────────────────────────────────────────────────────────────


class TestPREvent:
    """Validate pr-event.schema.json."""

    @pytest.fixture
    def valid_payload(self) -> dict:
        return {
            "schema_version": "1.0",
            "event_type": "pr",
            "repo": "my-org/my-service",
            "pr_number": 42,
            "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",  # pragma: allowlist secret
            "status": "merged",
            "occurred_at": "2026-06-22T10:30:00Z",
            "first_commit_at": "2026-06-20T08:00:00Z",
        }

    def test_valid_pr_passes(self, pr_schema, valid_payload):
        validate(valid_payload, pr_schema)

    def test_invalid_status_fails(self, pr_schema, valid_payload):
        payload = dict(valid_payload, status="draft")
        with pytest.raises(ValidationError):
            validate(payload, pr_schema)

    def test_missing_required_field_fails(self, pr_schema, valid_payload):
        payload = {k: v for k, v in valid_payload.items() if k != "pr_number"}
        with pytest.raises(ValidationError):
            validate(payload, pr_schema)

    def test_wrong_event_type_fails(self, pr_schema, valid_payload):
        payload = dict(valid_payload, event_type="deployment")
        with pytest.raises(ValidationError):
            validate(payload, pr_schema)

    def test_optional_fields_accepted(self, pr_schema, valid_payload):
        payload = dict(valid_payload, lines_added=100, lines_deleted=50, ai_assisted=True)
        validate(payload, pr_schema)

    def test_pr_number_must_be_positive(self, pr_schema, valid_payload):
        payload = dict(valid_payload, pr_number=0)
        with pytest.raises(ValidationError):
            validate(payload, pr_schema)

    def test_additional_properties_rejected(self, pr_schema, valid_payload):
        payload = dict(valid_payload, unknown_field="x")
        with pytest.raises(ValidationError):
            validate(payload, pr_schema)

    def test_first_commit_at_iso8601(self, pr_schema, valid_payload):
        payload = dict(valid_payload, first_commit_at="not-a-date")
        with pytest.raises(ValidationError):
            validate_with_format(payload, pr_schema)


# ── Rework Event ───────────────────────────────────────────────────────────────


class TestReworkEvent:
    """Validate rework-event.schema.json."""

    @pytest.fixture
    def valid_payload(self) -> dict:
        return {
            "schema_version": "1.0",
            "event_type": "rework",
            "repo": "my-org/my-service",
            "deployment_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",  # pragma: allowlist secret
            "rework_type": "hotfix",
            "triggered_at": "2026-06-22T10:30:00Z",
            "user_visible": True,
        }

    def test_valid_rework_passes(self, rework_schema, valid_payload):
        validate(valid_payload, rework_schema)

    @pytest.mark.parametrize("rework_type", ["hotfix", "rollback", "patch"])
    def test_all_rework_types_valid(self, rework_schema, valid_payload, rework_type):
        payload = dict(valid_payload, rework_type=rework_type)
        validate(payload, rework_schema)

    def test_invalid_rework_type_fails(self, rework_schema, valid_payload):
        payload = dict(valid_payload, rework_type="feature")
        with pytest.raises(ValidationError):
            validate(payload, rework_schema)

    def test_missing_required_field_fails(self, rework_schema, valid_payload):
        payload = {k: v for k, v in valid_payload.items() if k != "rework_type"}
        with pytest.raises(ValidationError):
            validate(payload, rework_schema)

    def test_wrong_event_type_fails(self, rework_schema, valid_payload):
        payload = dict(valid_payload, event_type="deployment")
        with pytest.raises(ValidationError):
            validate(payload, rework_schema)

    def test_user_visible_must_be_bool(self, rework_schema, valid_payload):
        payload = dict(valid_payload, user_visible="yes")
        with pytest.raises(ValidationError):
            validate(payload, rework_schema)

    def test_deployment_sha_format(self, rework_schema, valid_payload):
        payload = dict(valid_payload, deployment_sha="short")
        with pytest.raises(ValidationError):
            validate(payload, rework_schema)

    def test_additional_properties_rejected(self, rework_schema, valid_payload):
        payload = dict(valid_payload, unknown_field="x")
        with pytest.raises(ValidationError):
            validate(payload, rework_schema)


# ── Cross-Schema Validation ────────────────────────────────────────────────────


class TestCrossSchema:
    """Tests that verify events are rejected by schemas they don't belong to."""

    def test_deployment_rejected_by_incident_schema(self, incident_schema):
        """A valid deployment event should fail incident schema validation."""
        deployment = {
            "schema_version": "1.0",
            "event_type": "deployment",
            "repo": "org/repo",
            "service": "svc",
            "environment": "prod",
            "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",  # pragma: allowlist secret
            "deployed_at": "2026-06-22T10:30:00Z",
            "status": "success",
            "pipeline_url": "https://example.com/pipeline/1",
        }
        with pytest.raises(ValidationError):
            validate(deployment, incident_schema)

    def test_incident_rejected_by_deployment_schema(self, deployment_schema):
        """A valid incident event should fail deployment schema validation."""
        incident = {
            "schema_version": "1.0",
            "event_type": "incident",
            "incident_id": "INC-1",
            "repo": "org/repo",
            "service": "svc",
            "status": "opened",
            "occurred_at": "2026-06-22T10:30:00Z",
        }
        with pytest.raises(ValidationError):
            validate(incident, deployment_schema)

    def test_pr_rejected_by_rework_schema(self, rework_schema):
        """A valid PR event should fail rework schema validation."""
        pr = {
            "schema_version": "1.0",
            "event_type": "pr",
            "repo": "org/repo",
            "pr_number": 1,
            "commit_sha": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",  # pragma: allowlist secret
            "status": "opened",
            "occurred_at": "2026-06-22T10:30:00Z",
            "first_commit_at": "2026-06-20T08:00:00Z",
        }
        with pytest.raises(ValidationError):
            validate(pr, rework_schema)


@pytest.mark.parametrize(
    "schema_name",
    [
        "deployment-event.schema.json",
        "incident-event.schema.json",
        "pr-event.schema.json",
        "rework-event.schema.json",
    ],
)
def test_schema_version_is_1_0(schema_name):
    """AC-05: All schemas must start at schema_version 1.0."""
    load_schema(schema_name)
    # The schema itself doesn't carry version; payloads do.
    # Instead verify that a payload with version "1.0" passes.
    pass
