"""Unit tests for error models"""

import pytest

from src.agent_server.models.errors import AgentProtocolError, get_error_type


class TestAgentProtocolError:
    """Test AgentProtocolError model"""

    def test_error_with_details(self):
        """Test error creation with details"""
        error = AgentProtocolError(
            error="validation_error",
            message="Invalid input",
            details={"field": "name", "issue": "required"},
        )
        assert error.error == "validation_error"
        assert error.message == "Invalid input"
        assert error.details == {"field": "name", "issue": "required"}

    def test_error_without_details(self):
        """Test error creation without details"""
        error = AgentProtocolError(error="not_found", message="Resource not found")
        assert error.error == "not_found"
        assert error.message == "Resource not found"
        assert error.details is None


class TestGetErrorType:
    """Test get_error_type function"""

    def test_known_status_codes(self):
        """Test mapping of known status codes"""
        assert get_error_type(400) == "bad_request"
        assert get_error_type(401) == "unauthorized"
        assert get_error_type(403) == "forbidden"
        assert get_error_type(404) == "not_found"
        assert get_error_type(409) == "conflict"
        assert get_error_type(422) == "validation_error"
        assert get_error_type(500) == "internal_error"
        assert get_error_type(501) == "not_implemented"
        assert get_error_type(503) == "service_unavailable"

    def test_unknown_status_code(self):
        """Test unknown status code returns unknown_error"""
        assert get_error_type(418) == "unknown_error"
        assert get_error_type(999) == "unknown_error"
        assert get_error_type(200) == "unknown_error"
