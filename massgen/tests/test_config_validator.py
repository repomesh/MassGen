"""
Tests for configuration validator.

Tests cover:
- Valid configs (should pass)
- Missing required fields
- Invalid types and values
- Backend-specific validation
- V1 config rejection
- Warning generation
- Error reporting format
"""

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from massgen.config_validator import ConfigValidator, ValidationResult


class TestConfigValidator:
    """Test suite for ConfigValidator."""

    def test_valid_single_agent_config(self):
        """Test validation of a valid single agent config."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert not result.has_errors()

    def test_valid_multi_agent_config(self):
        """Test validation of a valid multi-agent config."""
        config = {
            "agents": [
                {
                    "id": "agent-1",
                    "backend": {"type": "openai", "model": "gpt-4o"},
                },
                {
                    "id": "agent-2",
                    "backend": {"type": "claude", "model": "claude-sonnet-4-5-20250929"},
                },
            ],
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert not result.has_errors()

    def test_valid_config_with_orchestrator(self):
        """Test validation of config with orchestrator settings."""
        config = {
            "agents": [
                {
                    "id": "agent-1",
                    "backend": {"type": "openai", "model": "gpt-4o"},
                },
            ],
            "orchestrator": {
                "voting_sensitivity": "balanced",
                "answer_novelty_requirement": "strict",
                "coordination": {
                    "enable_planning_mode": True,
                    "max_orchestration_restarts": 2,
                },
                "timeout": {
                    "orchestrator_timeout_seconds": 1800,
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert not result.has_errors()

    def test_unknown_coordination_key_warns(self):
        """Typos under orchestrator.coordination should be visible."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
            "orchestrator": {
                "coordination": {
                    "fast_interation_mode": True,
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert any("Unknown coordination config key" in warning.message for warning in result.warnings)
        assert any(warning.location == "orchestrator.coordination.fast_interation_mode" for warning in result.warnings)

    def test_unknown_orchestrator_key_warns(self):
        """Typos under orchestrator should be visible."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
            "orchestrator": {
                "voting_sensitivty": "balanced",
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert any("Unknown orchestrator config key" in warning.message for warning in result.warnings)
        assert any(warning.location == "orchestrator.voting_sensitivty" for warning in result.warnings)

    def test_unknown_timeout_settings_key_warns(self):
        """Typos under timeout_settings should be visible."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
            "timeout_settings": {
                "orchestrator_timout_seconds": 60,
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert any("Unknown timeout_settings key" in warning.message for warning in result.warnings)
        assert any(warning.location == "timeout_settings.orchestrator_timout_seconds" for warning in result.warnings)

    def test_subagent_timeout_bounds_are_validated(self):
        """Documented subagent timeout controls should fail fast when invalid."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
            "orchestrator": {
                "coordination": {
                    "subagent_default_timeout": 120,
                    "subagent_min_timeout": 300,
                    "subagent_max_timeout": 60,
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("subagent_min_timeout" in error.location for error in result.errors)

    def test_valid_config_with_ui(self):
        """Test validation of config with UI settings."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
            "ui": {
                "display_type": "rich_terminal",
                "logging_enabled": True,
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert not result.has_errors()

    def test_v1_config_rejected(self):
        """Test that V1 configs are rejected with helpful error."""
        config = {
            "models": ["gpt-4o", "claude-3-opus"],
            "num_agents": 2,
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert result.has_errors()
        assert any("V1 config format detected" in error.message for error in result.errors)
        assert any("migrate" in error.suggestion.lower() for error in result.errors if error.suggestion)

    def test_missing_agents_field(self):
        """Test error when neither 'agents' nor 'agent' is present."""
        config = {
            "orchestrator": {},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("must have either 'agents'" in error.message for error in result.errors)

    def test_both_agents_and_agent(self):
        """Test error when both 'agents' and 'agent' are present."""
        config = {
            "agents": [{"id": "a1", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "agent": {"id": "a2", "backend": {"type": "openai", "model": "gpt-4o"}},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("cannot have both 'agents' and 'agent'" in error.message for error in result.errors)

    def test_missing_agent_id(self):
        """Test error when agent is missing required 'id' field."""
        config = {
            "agent": {
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("missing required field 'id'" in error.message for error in result.errors)

    def test_missing_backend(self):
        """Test error when agent is missing required 'backend' field."""
        config = {
            "agent": {
                "id": "test-agent",
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("missing required field 'backend'" in error.message for error in result.errors)

    def test_duplicate_agent_ids(self):
        """Test error when multiple agents have the same ID."""
        config = {
            "agents": [
                {"id": "agent-1", "backend": {"type": "openai", "model": "gpt-4o"}},
                {"id": "agent-1", "backend": {"type": "claude", "model": "claude-sonnet-4-5-20250929"}},
            ],
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Duplicate agent ID" in error.message for error in result.errors)

    def test_missing_backend_type(self):
        """Test error when backend is missing required 'type' field."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"model": "gpt-4o"},
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("missing required field 'type'" in error.message for error in result.errors)

    def test_missing_backend_model(self):
        """Test error when backend is missing required 'model' field."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "chatcompletion"},  # Uses default_model="custom", requires explicit model
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("missing required field 'model'" in error.message for error in result.errors)

    def test_unknown_backend_type(self):
        """Test error when backend type is not recognized."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "unknown_backend", "model": "some-model"},
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Unknown backend type" in error.message for error in result.errors)

    def test_invalid_permission_mode(self):
        """Test error when permission_mode has invalid value."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "claude_code",
                    "model": "claude-sonnet-4-5-20250929",
                    "permission_mode": "invalid_mode",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Invalid permission_mode" in error.message for error in result.errors)

    def test_backend_capability_validation(self):
        """Test that backend capabilities are validated."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "lmstudio",  # lmstudio doesn't support web_search
                    "model": "custom",
                    "enable_web_search": True,
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("does not support" in error.message for error in result.errors)

    def test_invalid_display_type(self):
        """Test error when UI display_type is invalid."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
            "ui": {
                "display_type": "invalid_type",
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Invalid display_type" in error.message for error in result.errors)

    def test_invalid_voting_sensitivity(self):
        """Test error when voting_sensitivity is invalid."""
        config = {
            "agents": [
                {"id": "agent-1", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "voting_sensitivity": "invalid_value",
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Invalid voting_sensitivity" in error.message for error in result.errors)

    def test_invalid_context_path_permission(self):
        """Test error when context_paths permission is invalid."""
        config = {
            "agents": [
                {"id": "agent-1", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "context_paths": [
                    {"path": "/some/path", "permission": "invalid_permission"},
                ],
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Invalid permission" in error.message for error in result.errors)

    def test_warning_both_allowed_and_exclude_tools(self):
        """Test warning when both allowed_tools and exclude_tools are used."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "claude_code",
                    "model": "claude-sonnet-4-5-20250929",
                    "cwd": "workspace",
                    "allowed_tools": ["Read", "Write"],
                    "exclude_tools": ["Bash"],
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()  # No errors
        assert result.has_warnings()
        assert any("both 'allowed_tools' and 'exclude_tools'" in warning.message for warning in result.warnings)

    def test_no_warning_missing_system_message(self):
        """Test that missing system_message doesn't generate a warning."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        # Should not have warnings about missing system_message
        assert not any("system_message" in warning.message.lower() for warning in result.warnings)

    def test_no_warning_multi_agent_no_orchestrator(self):
        """Test that multi-agent setup without orchestrator doesn't generate a warning."""
        config = {
            "agents": [
                {"id": "agent-1", "backend": {"type": "openai", "model": "gpt-4o"}},
                {"id": "agent-2", "backend": {"type": "claude", "model": "claude-sonnet-4-5-20250929"}},
            ],
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        # Should not have warnings about missing orchestrator
        assert not any("orchestrator" in warning.message.lower() for warning in result.warnings)

    def test_invalid_type_field_types(self):
        """Test errors for wrong field types."""
        config = {
            "agent": {
                "id": 123,  # Should be string
                "backend": {
                    "type": "openai",
                    "model": "gpt-4o",
                    "enable_web_search": "yes",  # Should be boolean
                },
                "system_message": ["not", "a", "string"],  # Should be string
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert len(result.errors) >= 2  # Multiple type errors

    def test_validate_file_not_found(self):
        """Test validation of non-existent file."""
        validator = ConfigValidator()
        result = validator.validate_config_file("/nonexistent/config.yaml")

        assert not result.is_valid()
        assert any("Config file not found" in error.message for error in result.errors)

    def test_validate_yaml_file(self):
        """Test validation of a YAML file."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
        }

        # Create temporary YAML file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config, f)
            temp_path = f.name

        try:
            validator = ConfigValidator()
            result = validator.validate_config_file(temp_path)

            assert result.is_valid()
            assert not result.has_errors()
        finally:
            Path(temp_path).unlink()

    def test_validate_json_file(self):
        """Test validation of a JSON file."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
        }

        # Create temporary JSON file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            temp_path = f.name

        try:
            validator = ConfigValidator()
            result = validator.validate_config_file(temp_path)

            assert result.is_valid()
            assert not result.has_errors()
        finally:
            Path(temp_path).unlink()

    def test_validation_result_to_dict(self):
        """Test conversion of ValidationResult to dict."""
        result = ValidationResult()
        result.add_error("Test error", "test.location", "Test suggestion")
        result.add_warning("Test warning", "test.location", "Test suggestion")

        result_dict = result.to_dict()

        assert result_dict["valid"] is False
        assert result_dict["error_count"] == 1
        assert result_dict["warning_count"] == 1
        assert len(result_dict["errors"]) == 1
        assert len(result_dict["warnings"]) == 1
        assert result_dict["errors"][0]["message"] == "Test error"
        assert result_dict["warnings"][0]["message"] == "Test warning"

    def test_validation_result_format_errors(self):
        """Test error formatting."""
        result = ValidationResult()
        result.add_error("Test error message", "config.agent.backend", "Use correct type")

        formatted = result.format_errors()

        assert "Configuration Errors Found" in formatted
        assert "Test error message" in formatted
        assert "config.agent.backend" in formatted
        assert "Use correct type" in formatted

    def test_validation_result_format_warnings(self):
        """Test warning formatting."""
        result = ValidationResult()
        result.add_warning("Test warning message", "config.agent", "Add system_message")

        formatted = result.format_warnings()

        assert "Configuration Warnings" in formatted
        assert "Test warning message" in formatted
        assert "config.agent" in formatted
        assert "Add system_message" in formatted

    def test_tool_filtering_validation(self):
        """Test validation of tool filtering lists."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "claude_code",
                    "model": "claude-sonnet-4-5-20250929",
                    "allowed_tools": "not-a-list",  # Should be list
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("'allowed_tools' must be a list" in error.message for error in result.errors)

    def test_mcp_servers_validation(self):
        """Test that MCP server configs are validated."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "claude",
                    "model": "claude-sonnet-4-5-20250929",
                    "mcp_servers": "invalid-format",  # Should trigger MCP validator
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        # Should have error from MCP validation
        assert not result.is_valid()

    def test_complex_valid_config(self):
        """Test a complex but valid configuration."""
        config = {
            "agents": [
                {
                    "id": "researcher",
                    "backend": {
                        "type": "openai",
                        "model": "gpt-4o",
                        "enable_web_search": True,
                    },
                    "system_message": "You are a research assistant.",
                },
                {
                    "id": "analyst",
                    "backend": {
                        "type": "claude",
                        "model": "claude-sonnet-4-5-20250929",
                        "enable_code_execution": True,
                    },
                    "system_message": "You are a data analyst.",
                },
            ],
            "orchestrator": {
                "voting_sensitivity": "balanced",
                "answer_novelty_requirement": "lenient",
                "coordination": {
                    "enable_planning_mode": False,
                    "max_orchestration_restarts": 1,
                },
                "context_paths": [
                    {"path": "/data", "permission": "read"},
                    {"path": "/output", "permission": "write"},
                ],
                "timeout": {
                    "orchestrator_timeout_seconds": 3600,
                },
            },
            "ui": {
                "display_type": "rich_terminal",
                "logging_enabled": True,
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        # May have warnings but should have no errors
        assert not result.has_errors()


class TestCommonBadConfigs:
    """Test suite for common configuration mistakes users might make."""

    def test_v1_config_with_models_list(self):
        """Test V1 config with models list is rejected."""
        config = {
            "models": ["gpt-4o", "claude-3-opus"],
            "num_agents": 2,
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("V1 config format detected" in error.message for error in result.errors)
        assert any("migrate" in error.suggestion.lower() for error in result.errors if error.suggestion)

    def test_v1_config_with_model_configs(self):
        """Test V1 config with model_configs is rejected."""
        config = {
            "model_configs": {
                "gpt-4o": {"temperature": 0.7},
                "claude-3-opus": {"temperature": 0.5},
            },
            "agents": [{"id": "test"}],  # Even with agents present
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("V1 config" in error.message for error in result.errors)

    def test_missing_both_agents_and_agent(self):
        """Test config without agents or agent field."""
        config = {
            "orchestrator": {},
            "ui": {"display_type": "simple"},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("must have either 'agents'" in error.message for error in result.errors)

    def test_typo_in_backend_type(self):
        """Test common typo in backend type."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "openi",  # Common typo
                    "model": "gpt-4o",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Unknown backend type: 'openi'" in error.message for error in result.errors)
        assert any("openai" in error.suggestion for error in result.errors if error.suggestion)

    def test_wrong_case_backend_type(self):
        """Test wrong case in backend type."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "OpenAI",  # Should be lowercase
                    "model": "gpt-4o",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Unknown backend type" in error.message for error in result.errors)

    def test_unsupported_feature_for_backend(self):
        """Test requesting unsupported feature from backend."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "lmstudio",
                    "model": "custom",
                    "enable_web_search": True,  # lmstudio doesn't support this
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("does not support web_search" in error.message for error in result.errors)

    def test_boolean_as_string(self):
        """Test using string instead of boolean."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "openai",
                    "model": "gpt-4o",
                    "enable_web_search": "true",  # Should be boolean true
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("must be a boolean" in error.message for error in result.errors)

    def test_number_as_string(self):
        """Test using string for numeric field."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "timeout": {
                    "orchestrator_timeout_seconds": "1800",  # Should be number
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("must be a positive number" in error.message for error in result.errors)

    def test_invalid_display_type_typo(self):
        """Test typo in display_type."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {"type": "openai", "model": "gpt-4o"},
            },
            "ui": {
                "display_type": "detailed",  # Not a valid type
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Invalid display_type" in error.message for error in result.errors)
        assert any("rich_terminal" in error.suggestion for error in result.errors if error.suggestion)

    def test_invalid_permission_mode(self):
        """Test invalid permission_mode value."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "claude_code",
                    "model": "claude-sonnet-4-5-20250929",
                    "permission_mode": "auto",  # Not valid
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Invalid permission_mode" in error.message for error in result.errors)

    def test_context_path_wrong_permission(self):
        """Test wrong permission value in context_paths."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "context_paths": [
                    {"path": "/data", "permission": "readonly"},  # Should be "read"
                ],
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Invalid permission" in error.message for error in result.errors)
        assert any("'read' or 'write'" in error.suggestion for error in result.errors if error.suggestion)

    def test_negative_timeout(self):
        """Test negative timeout value."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "timeout": {
                    "orchestrator_timeout_seconds": -100,  # Negative
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("must be a positive number" in error.message for error in result.errors)

    def test_negative_max_restarts(self):
        """Test negative max_orchestration_restarts."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {
                    "max_orchestration_restarts": -1,  # Negative
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("must be a non-negative integer" in error.message for error in result.errors)

    def test_invalid_drift_conflict_policy(self):
        """Test invalid coordination.drift_conflict_policy value is rejected."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {
                    "drift_conflict_policy": "merge",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Invalid drift_conflict_policy" in error.message for error in result.errors)

    def test_valid_drift_conflict_policy(self):
        """Test valid coordination.drift_conflict_policy value passes validation."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {
                    "drift_conflict_policy": "prefer_presenter",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()

    def test_valid_background_subagents_config(self):
        """background_subagents should validate with supported fields."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {
                    "background_subagents": {
                        "enabled": True,
                        "injection_strategy": "tool_result",
                    },
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()

    def test_legacy_async_subagents_is_rejected(self):
        """async_subagents key should fail fast (hard-break rename)."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {
                    "async_subagents": {
                        "enabled": True,
                        "injection_strategy": "tool_result",
                    },
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("async_subagents" in error.message for error in result.errors)
        assert any("background_subagents" in (error.suggestion or "") for error in result.errors)

    def test_valid_subagent_runtime_mode_with_explicit_fallback(self):
        """Isolated runtime mode should allow explicit inherited fallback."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {
                    "subagent_runtime_mode": "isolated",
                    "subagent_runtime_fallback_mode": "inherited",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()

    def test_invalid_subagent_runtime_mode_is_rejected(self):
        """Unknown runtime mode values should fail validation."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {
                    "subagent_runtime_mode": "shared",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("subagent_runtime_mode" in error.location for error in result.errors)

    def test_invalid_subagent_runtime_fallback_mode_is_rejected(self):
        """Fallback mode must be inherited or null."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {
                    "subagent_runtime_mode": "isolated",
                    "subagent_runtime_fallback_mode": "isolated",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("subagent_runtime_fallback_mode" in error.location for error in result.errors)

    def test_subagent_runtime_fallback_requires_isolated_mode(self):
        """Fallback mode should be rejected when runtime mode is inherited."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {
                    "subagent_runtime_mode": "inherited",
                    "subagent_runtime_fallback_mode": "inherited",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("only be set when subagent_runtime_mode is 'isolated'" in error.message for error in result.errors)

    def test_subagent_host_launch_prefix_must_be_list_of_strings(self):
        """Host launch prefix should reject non-list values."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "coordination": {
                    "subagent_runtime_mode": "isolated",
                    "subagent_host_launch_prefix": "host-launch --exec",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("subagent_host_launch_prefix" in error.location for error in result.errors)

    def test_subagent_orchestrator_allows_inherit_mode_with_shared_common_agents(self):
        """inherit mode may coexist with shared common subagent_orchestrator agents."""
        config = {
            "agents": [
                {"id": "agent_a", "backend": {"type": "gemini", "model": "gemini-3-flash-preview"}},
                {"id": "agent_b", "backend": {"type": "openai", "model": "gpt-5-mini"}},
            ],
            "orchestrator": {
                "coordination": {
                    "enable_subagents": True,
                    "subagent_orchestrator": {
                        "enabled": True,
                        "inherit_spawning_agent_backend": True,
                        "agents": [
                            {"backend": {"type": "openai", "model": "gpt-5-mini"}},
                        ],
                    },
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid(), [error.message for error in result.errors]

    def test_subagent_orchestrator_inherit_mode_must_be_boolean(self):
        """inherit_spawning_agent_backend must be a boolean when provided."""
        config = {
            "agents": [
                {"id": "agent_a", "backend": {"type": "gemini", "model": "gemini-3-flash-preview"}},
            ],
            "orchestrator": {
                "coordination": {
                    "enable_subagents": True,
                    "subagent_orchestrator": {
                        "enabled": True,
                        "inherit_spawning_agent_backend": "yes",
                    },
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("inherit_spawning_agent_backend" in error.location for error in result.errors)

    def test_subagent_orchestrator_shared_child_team_types_accepts_string_lists(self):
        """shared_child_team_types should accept non-empty string lists."""
        config = {
            "agents": [
                {"id": "agent_a", "backend": {"type": "gemini", "model": "gemini-3-flash-preview"}},
            ],
            "orchestrator": {
                "coordination": {
                    "enable_subagents": True,
                    "subagent_orchestrator": {
                        "enabled": True,
                        "shared_child_team_types": ["round_evaluator", "builder"],
                    },
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid(), [error.message for error in result.errors]

    def test_subagent_orchestrator_shared_child_team_types_rejects_non_list(self):
        """shared_child_team_types should reject non-list values."""
        config = {
            "agents": [
                {"id": "agent_a", "backend": {"type": "gemini", "model": "gemini-3-flash-preview"}},
            ],
            "orchestrator": {
                "coordination": {
                    "enable_subagents": True,
                    "subagent_orchestrator": {
                        "enabled": True,
                        "shared_child_team_types": "builder",
                    },
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("shared_child_team_types" in error.location for error in result.errors)

    def test_subagent_orchestrator_shared_child_team_types_rejects_empty_entries(self):
        """shared_child_team_types should reject empty or whitespace entries."""
        config = {
            "agents": [
                {"id": "agent_a", "backend": {"type": "gemini", "model": "gemini-3-flash-preview"}},
            ],
            "orchestrator": {
                "coordination": {
                    "enable_subagents": True,
                    "subagent_orchestrator": {
                        "enabled": True,
                        "shared_child_team_types": ["round_evaluator", "  "],
                    },
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("shared_child_team_types" in error.location for error in result.errors)

    def test_agent_subagent_agents_must_be_a_list(self):
        """Top-level per-agent subagent_agents should reject non-list values."""
        config = {
            "agents": [
                {
                    "id": "agent_a",
                    "backend": {"type": "gemini", "model": "gemini-3-flash-preview"},
                    "subagent_agents": {"backend": {"type": "openai", "model": "gpt-5-mini"}},
                },
            ],
            "orchestrator": {
                "coordination": {
                    "enable_subagents": True,
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("subagent_agents" in error.location for error in result.errors)

    def test_agent_subagent_agents_accepts_agent_like_entries(self):
        """Top-level per-agent subagent_agents should accept the same agent-entry shape."""
        config = {
            "agents": [
                {
                    "id": "agent_a",
                    "backend": {"type": "gemini", "model": "gemini-3-flash-preview"},
                    "subagent_agents": [
                        {"id": "local_eval", "backend": {"type": "openai", "model": "gpt-5-mini"}},
                    ],
                },
            ],
            "orchestrator": {
                "coordination": {
                    "enable_subagents": True,
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid(), [error.message for error in result.errors]

    def test_agent_without_id(self):
        """Test agent missing id field (common mistake)."""
        config = {
            "agents": [
                {
                    # Missing id
                    "backend": {"type": "openai", "model": "gpt-4o"},
                },
            ],
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("missing required field 'id'" in error.message for error in result.errors)

    def test_agent_without_backend(self):
        """Test agent missing backend field (common mistake)."""
        config = {
            "agents": [
                {
                    "id": "test-agent",
                    # Missing backend
                },
            ],
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("missing required field 'backend'" in error.message for error in result.errors)

    def test_tools_list_with_non_strings(self):
        """Test tool filtering with non-string values."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "claude_code",
                    "model": "claude-sonnet-4-5-20250929",
                    "allowed_tools": ["Read", 123, "Write"],  # 123 is not a string
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("must be a string" in error.message for error in result.errors)

    def test_mcp_servers_wrong_type(self):
        """Test mcp_servers as wrong type."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "claude",
                    "model": "claude-sonnet-4-5-20250929",
                    "mcp_servers": "filesystem",  # Should be list or dict
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("MCP configuration error" in error.message for error in result.errors)

    def test_invalid_voting_sensitivity(self):
        """Test invalid voting_sensitivity value."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "voting_sensitivity": "medium",  # Should be lenient/balanced/strict
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Invalid voting_sensitivity" in error.message for error in result.errors)

    def test_invalid_answer_novelty(self):
        """Test invalid answer_novelty_requirement value."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "answer_novelty_requirement": "high",  # Should be lenient/balanced/strict
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Invalid answer_novelty_requirement" in error.message for error in result.errors)

    def test_valid_fairness_controls(self):
        """Test valid fairness settings pass validation."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "orchestrator": {
                "fairness_enabled": True,
                "fairness_lead_cap_answers": 1,
                "max_midstream_injections_per_round": 2,
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert not result.has_errors()

    def test_valid_checklist_report_gate_flag(self):
        """Test checklist_require_gap_report accepts boolean values."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"checklist_require_gap_report": False},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert not result.has_errors()

    def test_invalid_checklist_report_gate_flag_type(self):
        """Test checklist_require_gap_report must be a boolean."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"checklist_require_gap_report": "yes"},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("checklist_require_gap_report" in error.location for error in result.errors)

    def test_invalid_fairness_enabled_type(self):
        """Test fairness_enabled must be boolean."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"fairness_enabled": "yes"},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("fairness_enabled" in error.location for error in result.errors)

    def test_invalid_fairness_lead_cap(self):
        """Test fairness_lead_cap_answers must be non-negative integer."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"fairness_lead_cap_answers": -1},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("fairness_lead_cap_answers" in error.location for error in result.errors)

    def test_invalid_midstream_injection_cap(self):
        """Test max_midstream_injections_per_round must be positive integer."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"max_midstream_injections_per_round": 0},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("max_midstream_injections_per_round" in error.location for error in result.errors)

    def test_valid_defer_peer_updates_until_restart_flag(self):
        """defer_peer_updates_until_restart accepts booleans."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"defer_peer_updates_until_restart": True},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert not result.has_errors()

    def test_invalid_defer_peer_updates_until_restart_type(self):
        """defer_peer_updates_until_restart must be a boolean."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"defer_peer_updates_until_restart": "yes"},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("defer_peer_updates_until_restart" in error.location for error in result.errors)

    @pytest.mark.parametrize("value", [True, False, None])
    def test_valid_allow_midstream_peer_updates_before_checklist_submit(self, value):
        """allow_midstream_peer_updates_before_checklist_submit accepts bool/null."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"allow_midstream_peer_updates_before_checklist_submit": value},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert not result.has_errors()

    def test_invalid_allow_midstream_peer_updates_before_checklist_submit_type(self):
        """allow_midstream_peer_updates_before_checklist_submit must be bool/null."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"allow_midstream_peer_updates_before_checklist_submit": "nope"},
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("allow_midstream_peer_updates_before_checklist_submit" in error.location for error in result.errors)

    @pytest.mark.parametrize(
        "mode",
        [
            "final_only",
            "verification_and_final_only",
        ],
    )
    def test_valid_learning_capture_mode(self, mode):
        """Test learning_capture_mode accepts supported values."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {
                "coordination": {
                    "learning_capture_mode": mode,
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert not result.has_errors()

    def test_invalid_learning_capture_mode(self):
        """Test learning_capture_mode rejects unsupported values."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {
                "coordination": {
                    "learning_capture_mode": "invalid_mode",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("learning_capture_mode" in error.location for error in result.errors)

    @pytest.mark.parametrize("value", [True, False])
    def test_valid_disable_final_only_round_capture_fallback(self, value):
        """Test disable_final_only_round_capture_fallback accepts booleans."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {
                "coordination": {
                    "disable_final_only_round_capture_fallback": value,
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert not result.has_errors()

    def test_invalid_disable_final_only_round_capture_fallback(self):
        """Test disable_final_only_round_capture_fallback rejects non-boolean values."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {
                "coordination": {
                    "disable_final_only_round_capture_fallback": "yes",
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("disable_final_only_round_capture_fallback" in error.location for error in result.errors)

    def test_v1_max_rounds(self):
        """Test V1 max_rounds parameter is rejected."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "max_rounds": 5,  # V1 parameter
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("V1 config format detected" in error.message for error in result.errors)
        assert any("max_rounds" in error.message for error in result.errors)

    def test_v1_consensus_threshold(self):
        """Test V1 consensus_threshold parameter is rejected."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "consensus_threshold": 0.6,  # V1 parameter
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("V1 config format detected" in error.message for error in result.errors)
        assert any("consensus_threshold" in error.message for error in result.errors)

    def test_v1_voting_enabled(self):
        """Test V1 voting_enabled parameter is rejected."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "voting_enabled": True,  # V1 parameter
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("V1 config format detected" in error.message for error in result.errors)
        assert any("voting_enabled" in error.message for error in result.errors)

    def test_v1_multiple_keywords(self):
        """Test config with multiple V1 keywords."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "max_rounds": 5,
            "voting_enabled": True,
            "consensus_threshold": 0.6,
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("V1 config format detected" in error.message for error in result.errors)
        # Should mention all found V1 keywords
        error_messages = " ".join([e.message for e in result.errors])
        assert "max_rounds" in error_messages
        assert "voting_enabled" in error_messages
        assert "consensus_threshold" in error_messages


class TestMemoryValidation:
    """Test suite for memory configuration validation."""

    def test_valid_memory_config(self):
        """Test valid memory configuration."""
        config = {
            "agents": [
                {"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
            "memory": {
                "enabled": True,
                "conversation_memory": {
                    "enabled": True,
                },
                "persistent_memory": {
                    "enabled": True,
                    "on_disk": True,
                    "vector_store": "qdrant",
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-4.1-nano-2025-04-14",
                    },
                    "embedding": {
                        "provider": "openai",
                        "model": "text-embedding-3-small",
                    },
                    "qdrant": {
                        "mode": "server",
                        "host": "localhost",
                        "port": 6333,
                    },
                },
                "compression": {
                    "trigger_threshold": 0.75,
                    "target_ratio": 0.40,
                },
                "retrieval": {
                    "limit": 10,
                    "exclude_recent": True,
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert result.is_valid()
        assert not result.has_errors()

    def test_memory_enabled_wrong_type(self):
        """Test memory enabled with wrong type."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "memory": {
                "enabled": "yes",  # Should be boolean
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("'enabled' must be a boolean" in error.message for error in result.errors)

    def test_memory_qdrant_invalid_mode(self):
        """Test invalid qdrant mode."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "memory": {
                "persistent_memory": {
                    "qdrant": {
                        "mode": "distributed",  # Should be 'server' or 'local'
                    },
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("Invalid qdrant mode" in error.message for error in result.errors)
        assert any("'server' or 'local'" in error.suggestion for error in result.errors if error.suggestion)

    def test_memory_compression_out_of_range(self):
        """Test compression threshold out of valid range."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "memory": {
                "compression": {
                    "trigger_threshold": 1.5,  # Should be 0-1
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("must be between 0 and 1" in error.message for error in result.errors)

    def test_memory_retrieval_negative_limit(self):
        """Test negative retrieval limit."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "memory": {
                "retrieval": {
                    "limit": -5,  # Should be positive
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("must be a positive integer" in error.message for error in result.errors)

    def test_memory_qdrant_invalid_port(self):
        """Test invalid qdrant port."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "memory": {
                "persistent_memory": {
                    "qdrant": {
                        "mode": "server",
                        "port": 99999,  # Out of valid range
                    },
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("must be a valid port number" in error.message for error in result.errors)

    def test_memory_llm_provider_wrong_type(self):
        """Test llm provider with wrong type."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "memory": {
                "persistent_memory": {
                    "llm": {
                        "provider": 123,  # Should be string
                        "model": "gpt-4o",
                    },
                },
            },
        }

        validator = ConfigValidator()
        result = validator.validate_config(config)

        assert not result.is_valid()
        assert any("must be a string" in error.message for error in result.errors)


class TestGapReportModeValidation:
    """Tests for gap_report_mode config validation."""

    def test_valid_gap_report_mode_changedoc(self):
        """gap_report_mode='changedoc' is accepted."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"gap_report_mode": "changedoc"},
        }
        validator = ConfigValidator()
        result = validator.validate_config(config)
        assert result.is_valid()

    def test_valid_gap_report_mode_separate(self):
        """gap_report_mode='separate' is accepted."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"gap_report_mode": "separate"},
        }
        validator = ConfigValidator()
        result = validator.validate_config(config)
        assert result.is_valid()

    def test_valid_gap_report_mode_none(self):
        """gap_report_mode='none' is accepted."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"gap_report_mode": "none"},
        }
        validator = ConfigValidator()
        result = validator.validate_config(config)
        assert result.is_valid()

    def test_invalid_gap_report_mode_produces_error(self):
        """gap_report_mode with invalid value produces an error."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {"gap_report_mode": "invalid"},
        }
        validator = ConfigValidator()
        result = validator.validate_config(config)
        assert not result.is_valid()
        assert any("gap_report_mode" in error.message for error in result.errors)

    def test_copilot_docker_requires_network_mode(self):
        """Copilot in Docker mode without network_mode should produce an error."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "copilot",
                    "model": "gpt-5-mini",
                    "command_line_execution_mode": "docker",
                },
            },
        }
        validator = ConfigValidator()
        result = validator.validate_config(config)
        assert not result.is_valid()
        assert any("copilot" in error.message.lower() and "docker" in error.message.lower() and "network_mode" in error.message.lower() for error in result.errors)

    def test_copilot_docker_with_network_mode_passes(self):
        """Copilot in Docker mode with network_mode should pass."""
        config = {
            "agent": {
                "id": "test-agent",
                "backend": {
                    "type": "copilot",
                    "model": "gpt-5-mini",
                    "command_line_execution_mode": "docker",
                    "command_line_docker_network_mode": "bridge",
                },
            },
        }
        validator = ConfigValidator()
        result = validator.validate_config(config)
        # Should not have the network_mode error
        assert not any("copilot" in error.message.lower() and "docker" in error.message.lower() and "network_mode" in error.message.lower() for error in result.errors)

    def test_checklist_gated_without_changedoc_warns(self):
        """checklist_gated voting with enable_changedoc=False produces warning."""
        config = {
            "agents": [{"id": "test", "backend": {"type": "openai", "model": "gpt-4o"}}],
            "orchestrator": {
                "voting_sensitivity": "checklist_gated",
                "coordination": {"enable_changedoc": False},
            },
        }
        validator = ConfigValidator()
        result = validator.validate_config(config)
        assert result.has_warnings()
        assert any("checklist_gated" in w.message and "changedoc" in w.message.lower() for w in result.warnings)
