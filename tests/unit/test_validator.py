"""Unit tests for ingestion/api/validator.py.

Covers edge cases missed by the schema validation tests:
- _check_date_time with non-string input (line 21)
- _check_date_time with invalid datetime string (lines 25-26)
- ValidationDetail.to_dict() (line 72)
"""

from ingestion.api.validator import ValidationDetail, _check_date_time


class TestCheckDateTime:
    """Cover the uncovered branches in _check_date_time."""

    def test_non_string_input_returns_true(self):
        """Line 21: non-string input should return True (skip validation)."""
        assert _check_date_time(42) is True
        assert _check_date_time(None) is True
        assert _check_date_time([]) is True

    def test_invalid_datetime_string_returns_false(self):
        """Lines 25-26: invalid datetime strings should return False."""
        assert _check_date_time("not-a-date") is False
        assert _check_date_time("2024-13-01T00:00:00") is False  # month 13
        assert _check_date_time("") is False

    def test_valid_datetime_string_returns_true(self):
        """Valid ISO 8601 strings should return True."""
        assert _check_date_time("2024-01-15T10:30:00Z") is True
        assert _check_date_time("2024-01-15T10:30:00+00:00") is True


class TestValidationDetail:
    """Cover ValidationDetail.to_dict()."""

    def test_to_dict_with_field(self):
        """Line 72-75: to_dict with a field path."""
        detail = ValidationDetail(field=["body", "event_type"], message="Missing field")
        result = detail.to_dict()
        assert result == {
            "field": "body.event_type",
            "message": "Missing field",
        }

    def test_to_dict_without_field(self):
        """Line 72-75: to_dict with empty field list uses 'body'."""
        detail = ValidationDetail(field=[], message="General error")
        result = detail.to_dict()
        assert result == {
            "field": "body",
            "message": "General error",
        }
