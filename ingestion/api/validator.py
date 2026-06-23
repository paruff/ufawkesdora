"""Schema validator for canonical uFawkesDORA event schemas.

Validates incoming event payloads against the JSON Schema files in events/.
Returns structured 422 errors with field-level detail — not just "invalid".
"""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, ValidationError, validate
from jsonschema import FormatChecker

# ── Format checker for date-time ───────────────────────────────────────────────
# jsonschema does not ship with date-time format validation by default.


def _check_date_time(instance: str) -> bool:
    """Validate ISO 8601 date-time strings."""
    import datetime
    if not isinstance(instance, str):
        return True
    try:
        datetime.datetime.fromisoformat(instance)
        return True
    except (ValueError, TypeError):
        return False


_format_checker = FormatChecker()
_format_checker.checks("date-time")(_check_date_time)


# ── Schema registry ────────────────────────────────────────────────────────────

# Map event_type constant → schema filename
EVENT_TYPE_SCHEMA_MAP: dict[str, str] = {
    "deployment": "deployment-event.schema.json",
    "incident": "incident-event.schema.json",
    "pr": "pr-event.schema.json",
    "rework": "rework-event.schema.json",
}

# Cache loaded schemas
_schema_cache: dict[str, dict] = {}


def _get_schema_dir() -> Path:
    """Return the path to the events/ directory relative to this file."""
    return Path(__file__).resolve().parent.parent.parent / "events"


def _load_schema(filename: str) -> dict:
    """Load a JSON Schema file, caching it for subsequent calls."""
    if filename not in _schema_cache:
        schema_path = _get_schema_dir() / filename
        with open(schema_path) as f:
            _schema_cache[filename] = json.load(f)
    return _schema_cache[filename]


# ── Public API ─────────────────────────────────────────────────────────────────


class ValidationDetail:
    """Holds a single field-level validation error."""

    def __init__(self, field: list[str], message: str):
        self.field = field
        self.message = message

    def to_dict(self) -> dict:
        return {
            "field": ".".join(str(p) for p in self.field) if self.field else "body",
            "message": self.message,
        }


class ValidationResult:
    """Result of validating an event payload against its schema."""

    def __init__(self, valid: bool = False, errors: list[ValidationDetail] | None = None):
        self.valid = valid
        self.errors = errors or []

    def to_error_response(self) -> dict:
        return {
            "detail": [
                {"loc": ["body", e.field[0]] if e.field else ["body"],
                 "msg": e.message,
                 "type": "value_error"}
                for e in self.errors
            ]
        }


def validate_payload(payload: dict) -> ValidationResult:
    """Validate an event payload against its canonical schema.

    Steps:
    1. Check that ``event_type`` is present and known.
    2. Load the corresponding schema.
    3. Validate the payload, collecting field-level errors.

    Returns a ``ValidationResult`` — check ``.valid`` before using.
    """
    # Step 1: event_type must be present
    event_type = payload.get("event_type")
    if not event_type or not isinstance(event_type, str):
        return ValidationResult(errors=[
            ValidationDetail(
                field=["event_type"],
                message="field is required and must be a string",
            )
        ])

    # Step 2: event_type must be known
    schema_file = EVENT_TYPE_SCHEMA_MAP.get(event_type)
    if schema_file is None:
        return ValidationResult(errors=[
            ValidationDetail(
                field=["event_type"],
                message=f"unknown event_type '{event_type}'. "
                        f"Supported: {', '.join(EVENT_TYPE_SCHEMA_MAP.keys())}",
            )
        ])

    # Step 3: load schema and validate
    schema = _load_schema(schema_file)

    # Build a validator with format checking
    validator = Draft7Validator(schema, format_checker=_format_checker)

    errors: list[ValidationDetail] = []
    for error in sorted(validator.iter_errors(payload), key=lambda e: e.path):
        errors.append(ValidationDetail(
            field=list(error.path),
            message=error.message,
        ))

    if errors:
        return ValidationResult(errors=errors)

    return ValidationResult(valid=True)


def validate_payloads(payloads: list[dict]) -> list[ValidationResult]:
    """Validate multiple event payloads, returning one result per payload."""
    return [validate_payload(p) for p in payloads]
