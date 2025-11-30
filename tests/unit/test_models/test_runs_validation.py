"""Unit tests for Run model validations"""

import pytest
from pydantic import ValidationError

from src.agent_server.models.runs import RunCreate


class TestRunCreateValidation:
    """Test RunCreate validation"""

    def test_input_command_both_provided_with_non_empty_input(self):
        """Test that providing both input and command with non-empty input raises error"""
        with pytest.raises(ValidationError) as exc_info:
            RunCreate(
                assistant_id="test-assistant",
                input={"message": "hello"},
                command={"resume": True},
                stream_mode=["values"],
            )

        # Check error message contains "mutually exclusive"
        assert "mutually exclusive" in str(exc_info.value).lower()

    def test_input_command_both_empty(self):
        """Test that providing neither input nor command raises error"""
        with pytest.raises(ValidationError) as exc_info:
            RunCreate(assistant_id="test-assistant", stream_mode=["values"])

        # Check error message
        assert "must specify either" in str(exc_info.value).lower()

    def test_input_command_empty_dict_with_command(self):
        """Test that empty input dict with command is allowed (frontend compatibility)"""
        run = RunCreate(
            assistant_id="test-assistant",
            input={},  # Empty dict
            command={"resume": True},
            stream_mode=["values"],
        )
        assert run.input is None
        assert run.command == {"resume": True}

    def test_only_input_provided(self):
        """Test that only input is valid"""
        run = RunCreate(
            assistant_id="test-assistant",
            input={"message": "hello"},
            stream_mode=["values"],
        )
        assert run.input == {"message": "hello"}
        assert run.command is None

    def test_only_command_provided(self):
        """Test that only command is valid"""
        run = RunCreate(
            assistant_id="test-assistant",
            command={"resume": True, "args": {}},
            stream_mode=["values"],
        )
        assert run.command == {"resume": True, "args": {}}
        assert run.input is None
